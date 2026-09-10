from __future__ import annotations

import json
from typing import NoReturn

import httpx
from fastmcp.exceptions import ResourceError, ToolError

from .echo import UPSTREAM_ERROR, render
from .readonly import ReadOnlyViolation


def raise_for_status(
    resp: httpx.Response, *, context: str, resource: bool = False, body: bytes | None = None
) -> None:
    """Convert non-2xx HTTP responses to MCP errors. No-op for 2xx.

    `context` is a short label (tool name or resource URI) included in the message so
    the model can correlate the failure with the call site, and — where Aleph's status
    codes are ambiguous — the message names the likely cause and the next move.
    """
    if resp.is_success:
        return

    err_cls = ResourceError if resource else ToolError
    detail = _upstream_detail(resp, body)

    if resp.status_code == 401:
        raise err_cls(
            f"{context}: API key invalid or expired (401). "
            "Verify ALEPHCLIENT_API_KEY is current for this host."
        )
    if resp.status_code == 403:
        raise err_cls(
            f"{context}: authenticated but not authorised (403). "
            "This key lacks READ access to the requested collection, or the endpoint "
            "requires WRITE/admin rights that a read-only key does not have."
        )
    if resp.status_code == 404:
        raise err_cls(
            f"{context}: not found (404). Confirm the id exists and is visible to this key; "
            "call list_collections to see what is readable."
        )
    if resp.status_code == 400:
        raise err_cls(f"{context}: bad request (400).{detail}")
    if resp.status_code == 429:
        raise err_cls(
            f"{context}: rate limited (429) and retries are exhausted. "
            "Aleph limits anonymous callers to ~30 requests/minute; slow down or widen "
            "each query instead of issuing many narrow ones."
        )
    raise err_cls(f"{context}: unexpected HTTP {resp.status_code}.{detail}")


def raise_read_only(exc: ReadOnlyViolation, *, context: str, resource: bool = False) -> NoReturn:
    """Surface a client-side read-only refusal as the MCP error for this call site."""
    err_cls = ResourceError if resource else ToolError
    raise err_cls(
        f"{context}: {exc}. Refused locally by the read-only allowlist; this request was not "
        "sent to Aleph. If the instance redirected the read — SSO, or a canonical-host "
        "redirect — that is the likely cause rather than a write attempt. The target shown "
        "is untrusted: on a redirect hop it comes from the upstream's Location header."
    ) from exc


def _reported(exc: Exception) -> str:
    r"""How a transport exception is named in a model-visible refusal.

    Every raiser on this path shares it, so a new call site cannot copy half the pattern:
    the text is sanitised by `echo.UPSTREAM_ERROR` *and* labelled untrusted, because the
    label is what `echo` calls the mitigation here. `ProxyError`'s message is built by
    httpcore from the proxy's `CONNECT` reason phrase, which h11 admits as
    `([ \t]|[^\x00\s])*` -- every C0 control except NUL -- so a forward proxy authors this
    string outright, and the cap and the stripping are both load-bearing.

    A `ConnectTimeout` carries no message at all -- anyio raises a bare `TimeoutError` --
    so an unconditional parenthetical renders as empty quotes and reads as a broken
    message. The class name alone is the answer there.
    """
    detail = render(str(exc), UPSTREAM_ERROR)
    return (
        f'{type(exc).__name__}, untrusted transport text: "{detail}"'
        if detail
        else type(exc).__name__
    )


def raise_unreachable(
    exc: Exception, *, context: str, attempts: int, resource: bool = False
) -> NoReturn:
    """Surface an exhausted connection retry as the MCP error for this call site.

    The attempt count is in the message on purpose. Without it a caller cannot tell one
    unlucky connect from an instance that is down, so it retries by hand -- which is the
    behaviour the retry loop exists to remove.

    Raised only where nothing was delivered, which is what licences "No response was
    received": a caller re-asking after this one cannot duplicate an effect. A failure that
    may have been delivered goes to `raise_transport_failed`, which must not say it.
    """
    err_cls = ResourceError if resource else ToolError
    raise err_cls(
        f"{context}: could not reach Aleph after {attempts} "
        f"attempt{'' if attempts == 1 else 's'} ({_reported(exc)}). No response was received. "
        "This server issues only read requests, so no retry can have changed anything "
        "upstream. Check the host is reachable and the network path is up; retrying "
        "immediately will not help."
    ) from exc


def raise_tls_untrusted(exc: Exception, *, context: str, resource: bool = False) -> NoReturn:
    """Refuse a connect whose TLS handshake was not trusted.

    Deliberately gives both readings and recommends neither. A `CERTIFICATE_VERIFY_FAILED`
    against a self-signed instance and the same error against an intercepted connection are
    the same bytes here; which one it is depends on whether the operator expects to trust
    that certificate, which this process cannot know. Advising the setting would be advice
    to disable verification on the one occasion it worked.

    Not retried: a handshake failure is a statement about keys and names, not about load.
    """
    err_cls = ResourceError if resource else ToolError
    raise err_cls(
        f"{context}: the TLS handshake with Aleph was not trusted ({_reported(exc)}). No "
        "response was received. This is deterministic: retrying will not help, and the "
        "certificate will be rejected the same way until either it or this server's "
        "configuration changes. Either the instance serves a certificate this host does not "
        "trust -- a self-signed instance, which `ALEPH_MCP_VERIFY_TLS=false` exists for -- or "
        "something on the network path is intercepting the connection, in which case "
        "disabling verification would hide it. This server cannot tell the two apart."
    ) from exc


def raise_transport_failed(exc: Exception, *, context: str, resource: bool = False) -> NoReturn:
    """Refuse a transport failure that may have happened after the request was delivered.

    The one thing this must not do is claim no response was received. Read-side failures are
    indistinguishable from a request Aleph did receive -- the same argument that keeps them
    out of the retried set -- so the message says so, and leans on the guarantee that does
    hold regardless: every request this server issues is a read.

    Also the bucket an unrecognised `TransportError` subclass lands in. That is deliberate:
    the conservative claim is correct for a failure nobody has classified yet.
    """
    err_cls = ResourceError if resource else ToolError
    raise err_cls(
        f"{context}: the connection to Aleph failed ({_reported(exc)}). The request may have "
        "been received and its response lost, so this server cannot report whether Aleph "
        "acted on it -- but it issues only read requests, so nothing upstream can have "
        "changed either way. Retrying is safe. The class name above is the diagnosis: a read "
        "or write failure points at the network path, a pool timeout at this server's own "
        "concurrency limit, and a protocol error at one end disagreeing about HTTP."
    ) from exc


class ResponseTooLarge(Exception):
    """Marker mixed into the ceiling refusal so a caller can catch it by type instead of
    matching message text. `search_entities` re-asks with a smaller page on this.

    Deliberately carries no data. The crossing size was tried, so that a first shrink could
    aim proportionally at the ceiling instead of halving — but `_read_bounded` refuses at the
    chunk that crosses, so the reported size is always within a fraction of a percent of the
    ceiling however large the real body is. Measured: a body ten times over reported 1.0025x,
    making the aim a fixed 0.798 of the page. The attributes were inert, so they are gone,
    and with them the local `raise_too_large` needed to attach them — a local in the raising
    frame is kept alive by the exception's own traceback, which made every refusal a
    reference cycle the collector had to reach.
    """


class TooLargeToolError(ToolError, ResponseTooLarge):
    """The ceiling refusal on a tool call."""


class TooLargeResourceError(ResourceError, ResponseTooLarge):
    """The ceiling refusal on a resource read."""


def raise_too_large(size: int, limit: int, *, context: str, resource: bool = False) -> NoReturn:
    """Refuse an upstream response too big to decode into the model's context.

    The message is unchanged from when this refusal was untyped: it is what a model reads,
    and tests match on it.
    """
    err_cls = TooLargeResourceError if resource else TooLargeToolError
    raise err_cls(
        f"{context}: upstream response is {size} bytes, over the {limit}-byte ceiling this "
        "server decodes. Narrow the request — fewer facets, a smaller facet_size, a shorter "
        "text slice — rather than retrying it unchanged."
    )


# The JSON name for each Python type `json.loads` can produce. A Python name would be wrong
# in a message that says "JSON": JSON has no `str`, `int`, `float` or `bool`.
_JSON_TYPE_NAMES = {
    str: "string",
    list: "array",
    int: "number",
    float: "number",
    bool: "boolean",
    dict: "object",
    type(None): "null",
}


def raise_unusable_model(model: object, *, context: str, resource: bool = False) -> NoReturn:
    """Refuse a metadata body whose `model` is present but is not an object.

    Takes the offending value and derives its type name here, rather than accepting a string
    to interpolate. The distinction is the point: the value is upstream text, and a signature
    that cannot be handed foreign text at all keeps that guarantee in this function instead
    of in whichever call site copies it next. That is the convention `raise_unreachable`
    states for itself, and this is the cheaper way to meet it -- a type name has no payload,
    so nothing needs rendering or labelling.

    Told not to retry for the same reason `raise_unreachable` is: the bad shape is what the
    instance serves for this route, so a second call spends an upstream request to be
    refused identically.
    """
    err_cls = ResourceError if resource else ToolError
    kind = _JSON_TYPE_NAMES.get(type(model), "value")
    raise err_cls(
        f"{context}: this Aleph instance answered /api/2/metadata with a `model` that is a "
        f"JSON {kind} rather than an object, so its followthemoney ontology cannot be read. "
        "That is an upstream fault: nothing about the call can change it and retrying will "
        "not help. Entity captions fall back to a fixed property order in the meantime."
    )


# An error body worth quoting is never large. Parsing before checking would let the error
# path allocate without bound, which is the one path the transport ceiling cannot cover:
# the status is known before the body is.
_MAX_ERROR_BODY_BYTES = 64 * 1024


def _upstream_detail(resp: httpx.Response, body: bytes | None) -> str:
    """The `message` string from Aleph's JSON error body, labelled — or nothing.

    Everything else is dropped: an HTML page from a proxy in front of the instance, a
    stack fragment, a body too big to be an error message. Echoing a raw body would hand
    whoever can shape an error response a write primitive into the model's context, and
    would disclose whatever internal detail the upstream put in it.
    """
    if "json" not in resp.headers.get("content-type", "").lower():
        return ""
    raw = resp.content if body is None else body
    if len(raw) > _MAX_ERROR_BODY_BYTES:
        return ""
    try:
        payload = json.loads(raw)
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return ""
    quoted = render(message, UPSTREAM_ERROR)
    return f' Aleph reported (untrusted upstream text): "{quoted}"'
