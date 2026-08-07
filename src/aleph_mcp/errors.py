from __future__ import annotations

from typing import NoReturn

import httpx
from fastmcp.exceptions import ResourceError, ToolError

from .readonly import ReadOnlyViolation


def raise_for_status(resp: httpx.Response, *, context: str, resource: bool = False) -> None:
    """Convert non-2xx HTTP responses to MCP errors. No-op for 2xx.

    `context` is a short label (tool name or resource URI) included in the message so
    the model can correlate the failure with the call site, and — where Aleph's status
    codes are ambiguous — the message names the likely cause and the next move.
    """
    if resp.is_success:
        return

    err_cls = ResourceError if resource else ToolError
    detail = _upstream_detail(resp)

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
        "redirect — that is the likely cause rather than a write attempt."
    ) from exc


def raise_too_large(size: int, limit: int, *, context: str, resource: bool = False) -> NoReturn:
    """Refuse an upstream response too big to decode into the model's context."""
    err_cls = ResourceError if resource else ToolError
    raise err_cls(
        f"{context}: upstream response is {size} bytes, over the {limit}-byte ceiling this "
        "server decodes. Narrow the request — fewer facets, a smaller facet_size, a shorter "
        "text slice — rather than retrying it unchanged."
    )


# Aleph's own error text is upstream content, so it is quoted as data, kept to one line
# and kept short. It is an aid to the operator, not a channel: nothing that fails the
# shape below reaches the model at all.
_MAX_UPSTREAM_CHARS = 200


def _upstream_detail(resp: httpx.Response) -> str:
    """The `message` string from Aleph's JSON error body, labelled — or nothing.

    Everything else is dropped: an HTML page from a proxy in front of the instance, a
    stack fragment, a 500-character blob. Echoing a raw body would hand whoever can shape
    an error response a write primitive into the model's context, and would disclose
    whatever internal detail the upstream put in it.
    """
    if "json" not in resp.headers.get("content-type", "").lower():
        return ""
    try:
        payload = resp.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return ""
    # Collapsing whitespace is deliberate: it keeps a multi-line body from presenting as
    # separate lines of server-authored text.
    flat = _truncate(" ".join(message.split()), _MAX_UPSTREAM_CHARS)
    return f' Aleph reported (untrusted upstream text): "{flat}"'


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "…"
