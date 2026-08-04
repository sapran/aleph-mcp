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
    body = _truncate(resp.text, 500)

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
        raise err_cls(f"{context}: bad request (400). {body}")
    if resp.status_code == 429:
        raise err_cls(
            f"{context}: rate limited (429) and retries are exhausted. "
            "Aleph limits anonymous callers to ~30 requests/minute; slow down or widen "
            "each query instead of issuing many narrow ones."
        )
    raise err_cls(f"{context}: unexpected HTTP {resp.status_code}. {body}")


def raise_read_only(exc: ReadOnlyViolation, *, context: str, resource: bool = False) -> NoReturn:
    """Surface a client-side read-only refusal as the MCP error for this call site."""
    err_cls = ResourceError if resource else ToolError
    raise err_cls(f"{context}: {exc}. Refused locally — no request was sent to Aleph.") from exc


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "…"
