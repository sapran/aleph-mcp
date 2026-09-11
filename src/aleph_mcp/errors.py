from __future__ import annotations

import json
from typing import NoReturn

import httpx
from fastmcp.exceptions import ResourceError, ToolError

from .echo import UPSTREAM_ERROR, render
from .readonly import ReadOnlyViolation


def _budget_clause(attempts: int) -> str:
    """Why a retryable status stopped being retried, when the clock rather than the count
    ended it.

    The connect half of the transport has always named its cost -- `raise_unreachable` says
    "after N attempts" precisely so a caller can tell one unlucky hop from an instance that
    is down. The response half became able to end the loop the same way when it started
    charging its round trips, and a refusal that does not say so is indistinguishable from
    one that spent every attempt: measured, a route answering `503` after 30 seconds against
    a 25-second budget made one attempt and produced a message byte-identical to the
    four-attempt case.
    """
    return (
        f" Stopped after {attempts} attempt{'' if attempts == 1 else 's'}, by this call's "
        "wall-clock budget rather than by its retry count: ALEPH_MCP_TIMEOUT_SECS was spent "
        "on the round trips and the waits between them, so a slow instance is answered with "
        "fewer attempts than ALEPH_MCP_MAX_RETRIES allows. Raise the timeout if the instance "
        "is merely slow."
    )


def raise_for_status(
    resp: httpx.Response,
    *,
    context: str,
    resource: bool = False,
    body: bytes | None = None,
    attempts: int = 0,
    budget_spent: bool = False,
) -> None:
    """Convert non-2xx HTTP responses to MCP errors. No-op for 2xx.

    `context` is a short label (tool name or resource URI) included in the message so
    the model can correlate the failure with the call site, and — where Aleph's status
    codes are ambiguous — the message names the likely cause and the next move.

    `budget_spent` says the caller stopped retrying a retryable status because the
    wall-clock budget ran out with attempts still allowed. Only the two branches a
    retryable status can reach report it; the rest cannot be told this and do not ask.
    """
    if resp.is_success:
        return

    err_cls = ResourceError if resource else ToolError
    detail = _upstream_detail(resp, body)
    budget = _budget_clause(attempts) if budget_spent else ""

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
        # "retries are exhausted" is a claim about the retry count, so it is withheld
        # exactly when the count was not what ran out. Saying it anyway told the model to
        # slow down and widen its query -- a confident wrong diagnosis -- when the real
        # cause was a slow instance spending a wall-clock budget.
        exhausted = "" if budget_spent else " and retries are exhausted"
        raise err_cls(
            f"{context}: rate limited (429){exhausted}.{budget} "
            "Aleph limits anonymous callers to ~30 requests/minute; slow down or widen "
            "each query instead of issuing many narrow ones."
        )
    raise err_cls(f"{context}: unexpected HTTP {resp.status_code}.{detail}{budget}")


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


def raise_redirect_loop(
    exc: Exception, *, context: str, hops: int, resource: bool = False
) -> NoReturn:
    """Refuse a redirect chain that did not reach a final response inside this server's bound.

    Every hop was answered, so this must not claim the request was undelivered -- but unlike
    `raise_transport_failed` it is not a maybe in either direction: nothing was lost, there
    simply is no final response to return.

    Not retried, for the reason a TLS trust failure is not: the chain is what this host
    serves for this path, so the next attempt walks the identical hops. The bound is named
    because it is this server's rather than httpx's default of 20, and an operator reading
    the refusal has no other way to know which number was hit.
    """
    err_cls = ResourceError if resource else ToolError
    raise err_cls(
        f"{context}: the redirect chain from this host did not end within {hops} hops "
        f"({_reported(exc)}). Every hop answered, so nothing was lost -- there is simply no "
        "final response to return. This is deterministic: the same chain is served on every "
        "attempt, so it was not retried and retrying will not help. A loop here is an "
        "instance or proxy misconfiguration, typically an SSO interstitial or a "
        "canonical-host redirect that points back at itself. Every hop was still matched "
        "against this server's read-only allowlist before it was sent."
    ) from exc


def raise_undecodable_body(exc: Exception, *, context: str, resource: bool = False) -> NoReturn:
    """Refuse a response whose body does not honour the `Content-Encoding` it declares.

    The status and headers arrived, which is more than `raise_transport_failed` can say, so
    this says it. What it deliberately does *not* say is where the fault lies or whether
    retrying helps, because neither is decidable here: httpx's decoder raises on any chunk,
    not only the first, so an instance with a broken encoder and a body corrupted in transit
    by something on the network path arrive identically. Review measured the second case --
    a valid gzip body cut at its midpoint -- against an earlier draft of this message that
    excluded the network path and called the fault deterministic, and it was wrong on both
    counts.

    The decoder text is quoted through the same sanitising helper as every other foreign
    string. zlib's messages come from a fixed C string table and echo no input bytes: six
    hostile bodies -- injection text, `ESC` sequences, a truncated gzip header, a body of
    every byte value -- produced three distinct messages between them, none carrying any
    input. So the label is applied by convention here rather than against a known injection
    surface, which is the cheaper of the two mistakes to make.
    """
    err_cls = ResourceError if resource else ToolError
    raise err_cls(
        f"{context}: the response arrived but its body could not be decoded "
        f"({_reported(exc)}). Its status and headers were received; what failed is the body, "
        "which does not match the Content-Encoding it declares. This server cannot tell an "
        "instance that encodes its responses wrongly -- where retrying will fail the same "
        "way -- from a body corrupted in transit, where it may well succeed, so it does not "
        "advise either. Nothing upstream can have changed regardless: this server issues "
        "only read requests."
    ) from exc


def raise_transport_failed(exc: Exception, *, context: str, resource: bool = False) -> NoReturn:
    """Refuse a transport failure that may have happened after the request was delivered.

    The one thing this must not do is claim no response was received. Read-side failures are
    indistinguishable from a request Aleph did receive -- the same argument that keeps them
    out of the retried set -- so the message says so, and leans on the guarantee that does
    hold regardless: every request this server issues is a read.

    Also the bucket an unrecognised `httpx.RequestError` subclass lands in -- the whole
    family the transport catches, not only its `TransportError` half. That is deliberate: the
    conservative claim is correct for a failure nobody has classified yet. The closing
    sentence names `TransportError` shapes because those are the ones that reach it today;
    it is offered as a reading of the class name, not as an exhaustive list, and a new
    sibling arriving here is the signal to classify it rather than to widen that sentence.
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
# path allocate without bound, and the check below cannot be the only one: it runs on a body
# already in memory. The transport streams a failing response against this same constant --
# it is imported there, so the two cannot drift -- which is what makes it bound the
# allocation rather than only the quote.
MAX_ERROR_BODY_BYTES = 64 * 1024


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
    if len(raw) > MAX_ERROR_BODY_BYTES:
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
