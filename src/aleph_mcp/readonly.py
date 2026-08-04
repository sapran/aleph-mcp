from __future__ import annotations

import re

import httpx

# Every request this server may issue, as (method, path) pairs. Enforced on every
# outgoing httpx request, redirect hops included, so a mutating call cannot reach Aleph
# even when the API key would permit it. Extending this tuple is the only way to widen
# the surface; no argument, tool or redirect can.
_ENTITY_ID = r"[A-Za-z0-9._:-]+"
_COLLECTION_ID = r"[0-9]+"

_ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(rf"{path}/?"))
    for method, path in (
        ("GET", r"/api/2/metadata"),
        ("GET", r"/api/2/collections"),
        ("GET", rf"/api/2/collections/{_COLLECTION_ID}"),
        ("GET", rf"/api/2/collections/{_COLLECTION_ID}/xref"),
        ("GET", r"/api/2/entities"),
        ("GET", rf"/api/2/entities/{_ENTITY_ID}"),
        ("GET", rf"/api/2/entities/{_ENTITY_ID}/expand"),
        ("GET", rf"/api/2/entities/{_ENTITY_ID}/similar"),
        ("GET", rf"/api/2/entities/{_ENTITY_ID}/tags"),
        ("GET", r"/api/2/entitysets"),
        ("GET", rf"/api/2/entitysets/{_ENTITY_ID}/entities"),
        ("POST", r"/api/2/match"),
    )
)


class ReadOnlyViolation(RuntimeError):
    """A request outside the read-only allowlist was attempted and refused."""


def is_read_only(method: str, path: str) -> bool:
    """True when (method, path) is one of the Aleph read endpoints this server may call."""
    return any(m == method and p.fullmatch(path) for m, p in _ALLOWED)


async def enforce_read_only(request: httpx.Request) -> None:
    """httpx request hook: refuse anything not on the read-only allowlist.

    Runs for every request the client sends, redirect hops included, so the guarantee
    holds regardless of what the API key is permitted to do server-side.
    """
    if not is_read_only(request.method, request.url.path):
        raise ReadOnlyViolation(
            f"blocked {request.method} {request.url.path}: aleph-mcp is read-only and only "
            "calls a fixed allowlist of Aleph read endpoints"
        )
