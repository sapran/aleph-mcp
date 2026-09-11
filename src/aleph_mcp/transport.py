"""The one way a request leaves this process.

`AlephClient` asks this module for a decoded JSON body and gets back a dict or an MCP
error. Everything between those two points is here: the retry budget charged once across
sleep, connect and response time, the separate connect cap, the two streaming size bounds
— one for a body this server will decode, a much smaller one for a body it will only quote
from — the redirect ceiling, the read-only allowlist hook, and the status-to-MCP-error
translation.

One term stays outside the budget on purpose: the time spent reading the body of the
response the loop finally accepts. It is bounded by size rather than by the clock, because
abandoning a response already arriving would spend an upstream request and throw its answer
away.

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
    MAX_ERROR_BODY_BYTES,
    raise_for_status,
    raise_read_only,
    raise_redirect_loop,
    raise_tls_untrusted,
    raise_too_large,
    raise_transport_failed,
    raise_undecodable_body,
    raise_unparsable_body,
    raise_unreachable,
)
from .readonly import ReadOnlyViolation, read_only_hook

# A ceiling on the body this server will accept. Enforced while the response is streamed,
# so it bounds the allocation rather than describing it after the fact — httpx decodes
# Content-Encoding as it iterates, so a gzip bomb is refused at the same threshold as a
# plain body.
#
# It governs a *successful* body only, because it is a ceiling on what is decoded into the
# model's context and a failing body is never decoded into anything. A non-2xx is streamed
# against `MAX_ERROR_BODY_BYTES` instead — errors.py quotes at most a `message` out of it
# and drops any body over that bound before parsing, so the smaller bound is the real one
# and enforcing it here is what makes it bound the allocation too.
MAX_RESPONSE_BYTES = 25 * 1024 * 1024

# How many redirect hops one call may follow. httpx's own default is 20, which is a
# reasonable number for a general-purpose client and a poor one for a server that also
# retries: measured, an instance answering 302 with a Location back to the same path cost
# 21 upstream requests for a single tool call. The legitimate chains this server has met
# are one hop — Aleph's canonical-host redirect; the profile 302, which is not followed at
# all — so five leaves room for a reverse proxy that canonicalises as well.
#
# This is a bound on how far a chain is followed, never on what may be followed: every hop
# is matched against readonly.py's allowlist before it is sent, whatever this number is.
MAX_REDIRECTS = 5

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
    queue: list[BaseException] = [exc]
    while queue:
        current = queue.pop()
        if id(current) in seen:
            continue
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        # Both attributes, not `__cause__ or __context__`. Every mapper on this path does
        # `raise X from exc`, which sets the two to the same object, so the short-circuit is
        # correct against the installed stack -- but it makes the docstring's "anywhere in
        # this exception's chain" false in general, and a queue over both costs nothing.
        queue.extend(x for x in (current.__cause__, current.__context__) if x is not None)
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
            max_redirects=MAX_REDIRECTS,
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
        spent = 0
        by_budget = False
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
                        # The round trip is spend in the same sense a failed connect is, and
                        # it is charged in the same place: before the retry decision, so a
                        # slow answer both shortens its own backoff and can exhaust the
                        # budget on the spot. Measured with only the backoff charged: a route
                        # answering 503 after ten seconds cost four attempts and 47 seconds
                        # against a 25-second budget.
                        #
                        # What is charged is the time to the headers. The body read that may
                        # follow is bounded by size instead -- see the module docstring.
                        #
                        # `started` moves with the charge so that the handler below, which
                        # charges the same span again from the same mark, cannot double-count
                        # it. Today every arm reachable after this point raises, so the second
                        # charge is never read back; resetting keeps that true for an arm
                        # nobody has written yet, whose symptom would be a call quietly cut
                        # short by a budget short of one whole round trip.
                        budget -= self._monotonic() - started
                        started = self._monotonic()
                        # A zero delay still retries; only an exhausted budget stops the loop.
                        give_up = (
                            resp.status_code not in _RETRY_STATUS
                            or attempt == attempts
                            or budget <= 0
                        )
                        delay = 0.0 if give_up else min(_retry_delay(resp, attempt), budget)
                        if give_up:
                            # Which of the two ended the loop, recorded for the refusal. The
                            # status must have been retryable and the count must have had
                            # attempts left, or the budget is not what stopped anything.
                            spent = attempt
                            by_budget = (
                                resp.status_code in _RETRY_STATUS
                                and attempt < attempts
                                and budget <= 0
                            )
                            body = await self._read_body(resp, context=context, resource=resource)
                            break
                except (httpx.RequestError, ssl.SSLError) as e:
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
                    # The two certainties come first, because everything below them deals in
                    # maybes. Both are `httpx.RequestError` siblings of `TransportError`
                    # rather than members, which is why they escaped this seam entirely until
                    # the clause above widened: measured, a redirect loop reached the model as
                    # `Exceeded maximum allowed redirects.` and a body contradicting its own
                    # Content-Encoding as a raw zlib sentence, neither labelled, neither
                    # naming the call.
                    if isinstance(e, httpx.TooManyRedirects):
                        # Every hop was answered, so this is not the undelivered bucket --
                        # and not the possibly-delivered one either: nothing was lost, there
                        # is just no final response. Not retried, because the next attempt
                        # walks the identical chain.
                        #
                        # The hop count comes from the client that enforced it, not from the
                        # constant it was built with. The refusal's whole claim is that an
                        # operator can read which bound was hit, so it must not be able to
                        # name a number nothing applied.
                        raise_redirect_loop(
                            e,
                            context=context,
                            hops=self._http.max_redirects,
                            resource=resource,
                        )
                    if isinstance(e, httpx.DecodingError):
                        # Raised while a body is iterated, so the status and headers arrived.
                        # Reached only from a *successful* body's read: `_read_error_body`
                        # absorbs its own, because for a failing response the status is the
                        # better answer. A 200 is not a retried status, so nothing here
                        # decides whether to retry -- and the refusal deliberately does not
                        # claim to know, since a broken encoder and a body corrupted in
                        # transit look the same from here.
                        raise_undecodable_body(e, context=context, resource=resource)
                    # Delivery is settled *before* the TLS question, and the order is
                    # load-bearing. A TLS failure mid-body arrives as `ReadError` with an
                    # `ssl.SSLEOFError` in its chain, and testing the cause first reported it
                    # as a handshake trust failure that claimed no response was received --
                    # false for a read-side failure, and it named `ALEPH_MCP_VERIFY_TLS` for
                    # something that is not a trust problem. Only a failure before the headers
                    # arrived can carry a *trust* verdict; after them, a TLS fault is a broken
                    # connection to a response that may already have been served.
                    if isinstance(e, httpx.ProxyError):
                        # Undelivered: every `ProxyError` raise site in httpcore is a failed
                        # HTTP CONNECT or a SOCKS negotiation failure, none of which forwards
                        # anything to Aleph -- so `raise_unreachable`'s "No response was
                        # received" is true here, and its class name is what tells an operator
                        # the proxy rather than the instance refused.
                        #
                        # Not retried, for a different reason than its bucket: a proxy's
                        # refusal is a policy answer about this route, not a transient socket
                        # condition. Classified ahead of the fall-through because it is not a
                        # member of _CONNECT_ERRORS and would otherwise be swept into the
                        # possibly-delivered bucket, which for this class would be false.
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
        raise_for_status(
            resp,
            context=context,
            resource=resource,
            body=body,
            attempts=spent,
            budget_spent=by_budget,
        )
        # Guarded, because both shapes this can fail with are `ValueError` subclasses and
        # the tool seam used to translate that whole family: a 2xx serving an HTML
        # maintenance page reached the model as `Expecting value: line 1 column 1 (char 0)`,
        # in the shape reserved for a deliberate refusal. `body` is bytes, so `json.loads`
        # runs `detect_encoding` and decodes before parsing -- non-UTF-8 bytes raise
        # `UnicodeDecodeError`, a sibling of `JSONDecodeError` under `ValueError` rather
        # than a subclass, which is why this catches the base class and not either leaf.
        try:
            data: Any = jsonlib.loads(body)
        except ValueError as e:
            raise_unparsable_body(e, context=context, status=resp.status_code, resource=resource)
        # Only parsing is guarded, never shape. A bare array, string or number parsed fine
        # and keeps its wrapper; whether an envelope should be required before the rows are
        # trusted is a separate parked claim, and deciding it here would change what
        # `scope.py` sees without saying so anywhere.
        if not isinstance(data, dict):
            return {"results": data}
        return data

    async def _read_body(self, resp: httpx.Response, *, context: str, resource: bool) -> bytes:
        """Stream the body against whichever bound its status makes the real one.

        A success is read against the 25 MiB ceiling, which is what this server is willing to
        decode into the model's context. A failure is never decoded into anything: the most
        that reaches a caller is a `message` quoted out of it, and errors.py drops any body
        over `MAX_ERROR_BODY_BYTES` before parsing. Reading a failure against the larger
        ceiling therefore allocated up to 25 MiB nobody would read, and -- worse -- answered
        an oversized 502 with the ceiling refusal, hiding the status behind advice to narrow
        the request. Measured: a 502 with a plain body cost 4 requests and named the status;
        the same 502 with a 25 MiB body cost 16 through `search_entities`, because the
        ceiling refusal is the marker its shrink loop re-asks on.
        """
        if resp.is_success:
            return await self._read_bounded(resp, context=context, resource=resource)
        return await self._read_error_body(resp)

    async def _read_error_body(self, resp: httpx.Response) -> bytes:
        """The part of a failing body that could be quoted, or nothing.

        Empty bytes rather than a truncated prefix once the bound is crossed: that is
        already what `_upstream_detail` does with an over-sized body, and a prefix cut mid
        string is not JSON, so parsing one could only ever reach the same answer by a longer
        route. Stopping the iteration also means the rest of the body is never received.

        A read that fails part-way is answered the same way, and that is the point of doing
        it here rather than letting the exception out. The status is the one fact worth
        having about a failing response, and it is already in hand; letting a `ReadError` or
        a `DecodingError` out of this frame would hand the caller a network diagnosis or a
        Content-Encoding lecture with the `502` nowhere in it -- the same trap this whole
        change exists to close, one axis over. A body that could not be read is exactly as
        quotable as one too big to quote, which is the case already answered with `b""`.
        Nothing is lost: no failure is being swallowed, a more specific one is being
        preferred. It does not apply to a successful body, where the body *is* the answer --
        `_read_bounded` still lets its failures out.

        Unlike `_read_bounded` this does not clear its buffers before returning. It returns
        rather than raises, so no traceback keeps the frame -- and its locals -- alive.
        """
        total = 0
        chunks: list[bytes] = []
        try:
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_ERROR_BODY_BYTES:
                    return b""
                chunks.append(chunk)
        except (httpx.RequestError, ssl.SSLError):
            return b""
        return b"".join(chunks)

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
