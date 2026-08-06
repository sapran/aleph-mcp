from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

import httpx

# Every request this server may issue, as (method, path) pairs, where path is relative to
# the Aleph API root. Enforced on every outgoing httpx request, redirect hops included, so
# a mutating call cannot reach Aleph even when the API key would permit it. Extending this
# tuple is the only way to widen the surface; no argument, tool or redirect can.
#
# The method pin is load-bearing, not decorative. Two allowlisted GET paths are also live
# Aleph write routes, and only the absence of a matching (method, path) pair refuses them:
#
#   /api/2/entitysets/<id>     also registers DELETE, POST and PUT upstream
#                              (aleph/views/entitysets_api.py:144,181) — same path, verified
#                              against a live instance, which answers 405 for an unregistered
#                              method and 404 here.
#   /api/2/profiles/_pairwise  matches the GET rule for /api/2/profiles/<id>, because
#                              _ENTITY_ID admits `_`. It records a judgement and can create
#                              or merge a profile (aleph/views/profiles_api.py:207).
#
# So never drop the method from a pair, and never assume a path rule is safe because its
# read is. Do not narrow _ENTITY_ID to hex to exclude _pairwise by path either: Aleph ids are
# only conventionally uuid4().hex and the column is a 128-char string, so a narrowed pattern
# would refuse legitimate ids on an instance that ever minted one differently.
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
        ("GET", rf"/api/2/profiles/{_ENTITY_ID}"),
        ("GET", rf"/api/2/profiles/{_ENTITY_ID}/expand"),
        ("GET", rf"/api/2/profiles/{_ENTITY_ID}/similar"),
        ("GET", rf"/api/2/profiles/{_ENTITY_ID}/tags"),
        ("GET", r"/api/2/entitysets"),
        ("GET", rf"/api/2/entitysets/{_ENTITY_ID}"),
        ("GET", rf"/api/2/entitysets/{_ENTITY_ID}/entities"),
        ("POST", r"/api/2/match"),
    )
)


class ReadOnlyViolation(RuntimeError):
    """A request outside the read-only allowlist was attempted and refused."""


def is_read_only(method: str, path: str) -> bool:
    """True when (method, path) is one of the Aleph read endpoints this server may call.

    `path` is relative to the API root, i.e. with any base-URL prefix already removed.
    """
    return any(m == method and p.fullmatch(path) for m, p in _ALLOWED)


def read_only_hook(host: str) -> Callable[[httpx.Request], Awaitable[None]]:
    """Build the httpx request hook that pins every request to `host` and the allowlist.

    The returned hook runs for every request the client sends, redirect hops included, so
    the guarantee holds regardless of what the API key is permitted to do server-side. It
    refuses a request that leaves the configured host — an Aleph instance can redirect,
    and a POST /api/2/match body would otherwise be re-sent to the redirect target — and
    it strips the host's own path prefix before matching, so an Aleph mounted under
    https://example.org/aleph is checked on /api/2/... like any other.
    """
    base = httpx.URL(host)
    expected_host = base.host
    prefix = base.path.rstrip("/")

    async def enforce_read_only(request: httpx.Request) -> None:
        if request.url.host != expected_host:
            raise ReadOnlyViolation(
                f"blocked {request.method} {request.url}: this request leaves the configured "
                f"Aleph host {expected_host}"
            )
        path = request.url.path
        if prefix:
            if path == prefix:
                path = "/"
            elif path.startswith(f"{prefix}/"):
                path = path[len(prefix) :]
            else:
                raise ReadOnlyViolation(
                    f"blocked {request.method} {request.url}: this request leaves the "
                    f"configured Aleph base path {prefix}"
                )
        if not is_read_only(request.method, path):
            raise ReadOnlyViolation(
                f"blocked {request.method} {request.url}: aleph-mcp is read-only and only "
                "calls a fixed allowlist of Aleph read endpoints"
            )

    return enforce_read_only
