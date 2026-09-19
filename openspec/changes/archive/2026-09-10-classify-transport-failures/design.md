## Context

`Transport.request` has one `except _CONNECT_ERRORS` inside the retry loop and one
`except ReadOnlyViolation` around it. `_CONNECT_ERRORS` is `(ConnectError, ConnectTimeout)`, and
its comment already states the axis correctly — "nothing was delivered and nothing can be
duplicated" — but it is used as the *whole* classification rather than as one bucket of it. The
thirteen other `httpx.TransportError` subclasses have no handler anywhere between the wire and
fastmcp.

## Decisions

**Classify at the existing seam, not in a new one.** The `except` clause widens from
`_CONNECT_ERRORS` to `httpx.TransportError` and dispatches. Adding a second seam — an outer
handler around the loop, say — would split the budget accounting across two places, and the
budget charge (`budget -= self._monotonic() - started`) has to happen for a failure whichever
bucket it lands in.

**Two axes, four buckets, and the default is the conservative one.** Delivered-or-unknown is
the axis that decides what the message may claim; deterministic decides whether retrying is
spend or hope. The dispatch is written so that a `TransportError` subclass nobody thought about
— a future httpx release, or `CloseError`, which is unreachable through `stream()` today — falls
into "possibly delivered, do not retry, do not claim anything". A partition that fails open to
the safe answer needs no maintenance to stay correct; one that fails open to the wire is the
defect this change closes.

**A guard test enumerates `httpx.TransportError.__subclasses__` transitively.** The partition is
otherwise declared and never verified: it is exactly the "declared, never checked" shape noted
against `test_every_client_method_is_classified`. The test walks the live httpx module, so a new
subclass in a dependency bump fails the suite rather than silently escaping. It asserts each one
reaches a refusal carrying the call context — not which bucket, which would just restate the
implementation.

**TLS is detected by cause, and the walk is bounded.** httpcore raises `ConnectError` and keeps
the `ssl.SSLError` as `__cause__`, sometimes one level deeper. The walk follows `__cause__` and
`__context__` with a visited set: an exception chain can be cyclic (`raise x from x`, or a
re-raise inside its own handler), and this server already re-raises a cached exception, so an
unbounded walk here is a hang reachable from an upstream fault.

**`raise_tls_untrusted` names the setting rather than advising it.** The message states that the
certificate was not trusted, that this is deterministic, and that `ALEPH_MCP_VERIFY_TLS=false`
exists for a self-signed instance — without recommending it, because on a public instance the
same failure is what a MITM looks like. The distinction is not decidable from here, so the
message gives the operator both readings and picks neither.

**`ProxyError` is refused, not retried.** It is undelivered — a failed `CONNECT` means nothing
reached Aleph — so `raise_unreachable` states the truth, and the class name in the refusal is
what tells an operator the proxy rather than the instance refused. It gets one attempt: the
reason phrase is the proxy's own answer about this route, not a transient socket condition.

**`raise_transport_failed` must not claim delivery either way.** `raise_unreachable`'s "No
response was received" is load-bearing for a caller deciding whether to re-ask, and it would be
a lie for `ReadError`. The new message says the request may have been received, and keeps the
one thing that is certain regardless: this server issues only read requests, so nothing upstream
can have changed.

## Risks

**A refusal where an exception used to escape is still a behaviour change.** Anything catching
`httpx.ReadError` around a tool call now sees a `ToolError`. Inside this repo nothing does, and
across the MCP boundary the exception was never visible as a type — only as rendered text — so
the blast radius is the message.

**The TLS branch removes three retries.** That is the point, but it means a genuinely transient
handshake failure now fails on the first attempt. Accepted: `ssl.SSLError` from a handshake is a
statement about keys and names, not about load.
