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


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    """Scheme, host and explicit port, with the scheme's default port filled in.

    Resolving the default is what makes `https://aleph.test` and `https://aleph.test:443`
    the same origin, so a redirect cannot restate the pinned host in a form that compares
    unequal — or, worse, reach a different service by naming a port at all.
    """
    return (
        url.scheme,
        url.host,
        url.port if url.port is not None else _DEFAULT_PORTS.get(url.scheme),
    )


# On a redirect hop the request URL is built from the upstream's Location header, so the
# refusal message is a path by which an upstream writes into the model's context. Emit a
# bounded rendering: no userinfo (an f-string on httpx.URL yields the unmasked form), no
# query string (it carries the analyst's own search terms), no control characters, and a
# length cap — the same treatment errors.py gives upstream error text.
_MAX_TARGET_CHARS = 120


def _describe(url: httpx.URL) -> str:
    """A bounded, credential-free rendering of a URL that may be upstream-controlled."""
    port = f":{url.port}" if url.port is not None else ""
    target = f"{url.scheme}://{url.host}{port}{url.path}"
    target = "".join(ch if ch.isprintable() else "\ufffd" for ch in target)
    if len(target) > _MAX_TARGET_CHARS:
        target = target[:_MAX_TARGET_CHARS] + "…"
    return target


def read_only_hook(host: str) -> Callable[[httpx.Request], Awaitable[None]]:
    """Build the httpx request hook that pins every request to `host` and the allowlist.

    The returned hook runs for every request the client sends, redirect hops included, so
    the guarantee holds regardless of what the API key is permitted to do server-side. It
    refuses a request that leaves the configured origin — an Aleph instance can redirect,
    and a POST /api/2/match body would otherwise be re-sent to the redirect target — and
    it strips the host's own path prefix before matching, so an Aleph mounted under
    https://example.org/aleph is checked on /api/2/... like any other.

    The pin is on the whole origin, not the hostname: comparing hostnames alone would let
    a redirect downgrade https to http, or point at a different service on another port of
    the same machine, and still be matched against the read allowlist.
    """
    base = httpx.URL(host)
    expected = _origin(base)
    prefix = base.path.rstrip("/")

    async def enforce_read_only(request: httpx.Request) -> None:
        target = _describe(request.url)
        if _origin(request.url) != expected:
            scheme, name, port = expected
            raise ReadOnlyViolation(
                f"blocked {request.method} {target}: this request leaves the configured "
                f"Aleph origin {scheme}://{name}:{port}"
            )
        path = request.url.path
        if prefix:
            if path == prefix:
                path = "/"
            elif path.startswith(f"{prefix}/"):
                path = path[len(prefix) :]
            else:
                raise ReadOnlyViolation(
                    f"blocked {request.method} {target}: this request leaves the "
                    f"configured Aleph base path {prefix}"
                )
        if not is_read_only(request.method, path):
            raise ReadOnlyViolation(
                f"blocked {request.method} {target}: aleph-mcp is read-only and only "
                "calls a fixed allowlist of Aleph read endpoints"
            )

    return enforce_read_only
