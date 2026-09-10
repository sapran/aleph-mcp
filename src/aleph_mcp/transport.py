"""The one way a request leaves this process.

`AlephClient` asks this module for a decoded JSON body and gets back a dict or an MCP
error. Everything between those two points is here: the retry budget charged once across
sleep and connect time, the separate connect cap, the streaming size ceiling, the
read-only allowlist hook, and the status-to-MCP-error translation.

Nothing in here knows what an Aleph payload looks like. That is the point of the seam: the
retry budget and the gzip ceiling can be tested against a route answering `{}`, and the
endpoints above can be tested without an upstream that also has to be slow.

The one recovery this seam deliberately does *not* absorb is `search_entities`' page
shrink. The refusal is exposed by type — `ResponseTooLarge` from errors.py — and the
caller keeps the loop, because re-asking is a search-query decision (rebuild the page
params, report a truncated page, offer an offset to resume from) rather than a transport
one. The reasoning is written out at the shrink loop in client.py.
"""

from __future__ import annotations

import asyncio
import json as jsonlib
import ssl
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx
from fastmcp.exceptions import ResourceError, ToolError

from .config import Settings
from .errors import (
    raise_for_status,
    raise_read_only,
    raise_tls_untrusted,
    raise_too_large,
    raise_transport_failed,
    raise_unreachable,
)
from .readonly import ReadOnlyViolation, read_only_hook

# A ceiling on the body this server will accept. Enforced while the response is streamed,
# so it bounds the allocation rather than describing it after the fact — httpx decodes
# Content-Encoding as it iterates, so a gzip bomb is refused at the same threshold as a
# plain body. The error path has its own, much smaller bound in errors.py, because there
# the status is known before the body is.
MAX_RESPONSE_BYTES = 25 * 1024 * 1024

# The connect phase gets its own, much shorter ceiling than the rest of the request. A
# handshake that takes a minute will not produce a useful answer, and the retry loop has
# to be able to afford more than one attempt inside the same budget: a bare float timeout
# gives httpx one value for every phase, so connect alone would consume the whole of it.
MAX_CONNECT_SECS = 10.0

# Total time a single tool call may spend asleep between retries. The per-request httpx
# timeout does not cover asyncio.sleep, so without this an upstream answering every
# attempt with `Retry-After: 30` decides how long the caller's tool invocation hangs.
MAX_RETRY_SLEEP_SECS = 30.0

# httpx types query values permissively; match it so no cast is needed at the call site.
Query = list[tuple[str, str | int | float | bool | None]]

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

# Failures raised before the request left this process, and plausibly transient. Retrying
# them is safe whatever the method, because nothing was delivered and nothing can be
# duplicated. Read-side failures (ReadError, ReadTimeout, RemoteProtocolError) are
# deliberately excluded: they are indistinguishable from a request Aleph did receive.
#
# This is one bucket of the classification in `_classify`, not the whole of it. It used to
# be the whole of it, which is how the other thirteen `httpx.TransportError` subclasses
# reached the model as raw httpx exceptions.
_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


def _has_tls_cause(exc: BaseException) -> bool:
    """Whether an `ssl.SSLError` is anywhere in this exception's chain.

    httpcore raises `ConnectError` for a failed handshake and keeps the `ssl.SSLError` as
    `__cause__`, sometimes one level deeper, so the cause is the only place the real
    diagnosis exists -- `CERTIFICATE_VERIFY_FAILED` is otherwise legible only inside the
    quoted transport text, which is exactly what a model should not have to parse.

    The walk is bounded by a visited set rather than by trust. An exception chain can be
    cyclic -- `raise x from x`, or a re-raise inside its own handler -- and this server
    re-raises a cached exception on the metadata path, so an unbounded walk here would be a
    hang reachable from an upstream fault.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _backoff_delay(attempt: int) -> float:
    return min(MAX_RETRY_SLEEP_SECS, float(2 ** (attempt - 1)))


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(MAX_RETRY_SLEEP_SECS, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return _backoff_delay(attempt)


class Transport:
    """Owns the one httpx.AsyncClient; the caller closes it with aclose().

    Only what `readonly.py` allows ever leaves: the allowlist is installed as an httpx
    request event hook, so it is evaluated for the originating request and for every
    redirect hop, whatever the API key is permitted to do server-side. That hook is why
    this class builds the httpx client rather than accepting one — a caller able to supply
    its own could supply one without the guard.

    `monotonic` is injected rather than read from `time` here. The retry budget is
    wall-clock and a hanging connect is its dominant term, so a test that cannot move the
    clock is blind to the term that dominates it — and a mocked transport raises instantly,
    which means the real clock cannot express a slow connect at all.
    """

    def __init__(
        self, settings: Settings, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._settings = settings
        self._monotonic = monotonic
        self._http = httpx.AsyncClient(
            base_url=settings.host,
            headers={
                "Authorization": f"ApiKey {settings.api_key.get_secret_value()}",
                "Accept": "application/json",
                "User-Agent": "aleph-mcp",
            },
            timeout=httpx.Timeout(
                settings.timeout_secs,
                connect=min(MAX_CONNECT_SECS, settings.timeout_secs),
            ),
            verify=settings.verify_tls,
            follow_redirects=True,
            event_hooks={"request": [read_only_hook(settings.host)]},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        context: str,
        params: Query | None = None,
        json: Any | None = None,
        resource: bool = False,
        follow_redirects: bool | None = None,
        on_redirect: Callable[[httpx.Response], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        attempts = self._settings.max_retries
        query = httpx.QueryParams(params) if params else None
        resp: httpx.Response | None = None
        body = b""
        follow = self._http.follow_redirects if follow_redirects is None else follow_redirects
        # One tool call, one budget. Each hop's backoff is clamped, but an upstream that
        # answers every attempt with a Retry-After — or a host that swallows every connect
        # until the connect timeout fires — would otherwise multiply that clamp by
        # max_retries and decide how long the caller hangs.
        budget = self._settings.timeout_secs
        try:
            for attempt in range(1, attempts + 1):
                started = self._monotonic()
                # Whether the response headers arrived. This is the delivery axis measured
                # rather than inferred: an exception class only says which phase *usually*
                # raises it, and `ssl.SSLError` can come from a handshake or from decrypting
                # a record mid-body. Anything raised after this point may have been acted on
                # upstream, whatever its class.
                delivered = False
                try:
                    async with self._http.stream(
                        method, path, params=query, json=json, follow_redirects=follow
                    ) as resp:
                        delivered = True
                        if on_redirect is not None and resp.is_redirect:
                            return on_redirect(resp)
                        # A zero delay still retries; only an exhausted budget stops the loop.
                        give_up = (
                            resp.status_code not in _RETRY_STATUS
                            or attempt == attempts
                            or budget <= 0
                        )
                        delay = 0.0 if give_up else min(_retry_delay(resp, attempt), budget)
                        if give_up:
                            body = await self._read_bounded(
                                resp, context=context, resource=resource
                            )
                            break
                except (httpx.TransportError, ssl.SSLError) as e:
                    # `ssl.SSLError` is caught alongside because it is *not* an
                    # `httpx.TransportError`: measured, a `BAD_RECORD_MAC` reached the model
                    # as `Error calling tool 'list_collections': [SSL: BAD_RECORD_MAC] ...`,
                    # unlabelled and with no call context, straight past a clause naming only
                    # httpx. It is caught but deliberately *not* routed to the trust bucket:
                    # httpcore's `start_tls` maps `ssl.SSLError` to `ConnectError`, so a
                    # handshake fault can never arrive bare, and the read and write exception
                    # maps have no `ssl.SSLError` entry -- which leaves the read or write
                    # phase as the only way one reaches here, i.e. exactly the case that must
                    # not claim nothing was received. It falls through to the conservative
                    # refusal like any other unclassified member.
                    #
                    # A refusal this server already raised inside the block wins over a
                    # failure raised while the block unwinds. `aclose()` on a broken socket
                    # raises `CloseError` during `__aexit__`, which *replaces* the pending
                    # exception -- measured: it turned the ceiling refusal into "the
                    # connection to Aleph failed" and destroyed the `ResponseTooLarge`
                    # marker `search_entities` catches by type to shrink an oversized page,
                    # so the shrink loop silently stopped working. The refusal is the
                    # answer; a close failure after it is noise.
                    #
                    # This assumes no caller re-issues a request from *inside* an
                    # `except ToolError/ResourceError` handler: such a caller would carry the
                    # handled refusal in `__context__` and get it re-raised in place of the
                    # real transport failure. The one caller that re-asks -- `search_entities`
                    # shrinking an oversized page -- re-issues on the next loop iteration,
                    # after the handler has exited and Python has cleared that state.
                    pending = e.__context__
                    if isinstance(pending, ToolError | ResourceError):
                        raise pending from None
                    # A failed attempt is spend, not just the sleep after it: it can burn the
                    # whole connect phase, which is the larger term. Charging only the backoff
                    # would let max_retries slow connects hold one tool call open for a
                    # multiple of the budget — the case MAX_CONNECT_SECS also bounds. Charged
                    # before the dispatch, so it is charged whichever bucket the failure lands
                    # in.
                    budget -= self._monotonic() - started
                    # The classification, on two axes: could the request have been delivered,
                    # and is the failure deterministic. Dispatching on the value here rather
                    # than narrowing the `except` clause is the whole point -- the fall-through
                    # is `raise_transport_failed`, so a subclass nobody has classified gets the
                    # conservative answer instead of the wire.
                    #
                    # Delivery is settled *before* the TLS question, and the order is
                    # load-bearing. A TLS failure mid-body arrives as `ReadError` with an
                    # `ssl.SSLEOFError` in its chain, and testing the cause first reported it
                    # as a handshake trust failure that claimed no response was received --
                    # false for a read-side failure, and it named `ALEPH_MCP_VERIFY_TLS` for
                    # something that is not a trust problem. Only a failure before the headers
                    # arrived can carry a *trust* verdict; after them, a TLS fault is a broken
                    # connection to a response that may already have been served.
                    if isinstance(e, httpx.ProxyError):
                        # Undelivered -- a failed CONNECT means nothing reached Aleph -- so
                        # `raise_unreachable` states the truth, and its class name is what
                        # tells an operator the proxy rather than the instance refused.
                        # Deliberately not retried and deliberately not in _CONNECT_ERRORS: a
                        # CONNECT that reached the proxy is not obviously undelivered, which
                        # is the argument that correctly keeps ReadError out, and the reason
                        # phrase is the proxy's answer about this route rather than a
                        # transient socket condition. Classified ahead of the fall-through
                        # precisely because it is not a member of _CONNECT_ERRORS.
                        raise_unreachable(e, context=context, attempts=attempt, resource=resource)
                    if delivered or not isinstance(e, _CONNECT_ERRORS):
                        raise_transport_failed(e, context=context, resource=resource)
                    if _has_tls_cause(e):
                        raise_tls_untrusted(e, context=context, resource=resource)
                    if attempt == attempts or budget <= 0:
                        raise_unreachable(e, context=context, attempts=attempt, resource=resource)
                    delay = min(_backoff_delay(attempt), budget)
                # One place where the budget is spent, whichever path bound the delay.
                budget -= delay
                await asyncio.sleep(delay)
        except ReadOnlyViolation as e:
            raise_read_only(e, context=context, resource=resource)
        assert resp is not None
        raise_for_status(resp, context=context, resource=resource, body=body)
        data: Any = jsonlib.loads(body)
        if not isinstance(data, dict):
            return {"results": data}
        return data

    async def _read_bounded(self, resp: httpx.Response, *, context: str, resource: bool) -> bytes:
        """Accumulate the body, refusing the moment the running total crosses the ceiling.

        The refusal has to happen here rather than after the read: httpx content-decodes
        as it iterates, so this is the only point at which a compressed body's expanded
        size is knowable before it has all been allocated.
        """
        total = 0
        chunks: list[bytes] = []
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                # Drop both buffers before raising. The exception's traceback keeps this
                # frame alive for as long as the exception lives, and `search_entities` can
                # reach this point MAX_SEARCH_SHRINKS + 1 times in one call. Measured
                # without the clear: 106 MiB of real resident growth for a 25 MiB ceiling,
                # 4.16x.
                #
                # `chunk` matters as much as `chunks` and is easy to miss. For a
                # `Content-Encoding: gzip` body the ceiling is crossed on the first decoded
                # chunk, so the list is empty and `chunk` is the whole of it — and httpx
                # decodes with no `max_length`, so it is the one buffer nothing bounds.
                chunks.clear()
                chunk = b""
                raise_too_large(total, MAX_RESPONSE_BYTES, context=context, resource=resource)
            chunks.append(chunk)
        return b"".join(chunks)
