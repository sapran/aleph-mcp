## Context

See `proposal.md` — Why for the four measurements. All four live in one method,
`Transport.request`, and in the half of it that handles a response rather than a failed connect.
The connect half was hardened twice (`classify-transport-failures`, and the budget charge before
it); the response half was left with the loop's original shape.

Two constraints shape the approach:

- `search_entities` catches `ResponseTooLarge` by type to shrink an oversized page. What the
  transport raises therefore decides whether the shrink loop runs at all, which is why the
  oversized-`502` fix belongs at the transport and not in the loop.
- `readonly.py` is installed as an httpx request event hook and fires per redirect hop. Anything
  done to the redirect chain must leave that untouched: the bound decides when to stop following,
  never what may be followed.

## Goals / Non-Goals

**Goals:**

- One wall-clock budget per tool call, charged by both halves of every attempt.
- A failing status reported as that status, whatever the size of its body.
- Every `httpx.RequestError` refused through this server's error path, with the two known
  escapees each given a message that says what actually happened.
- A redirect ceiling this project chose.

**Non-Goals:**

- Changing `MAX_RESPONSE_BYTES`, `MAX_RETRY_SLEEP_SECS`, `MAX_CONNECT_SECS` or the retry-status
  set. This change accounts for the budget; it does not re-tune it.
- Abandoning a response already in flight when the budget runs out. The overrun of at most one
  request is stated in the spec rather than engineered away: a cancelled read is a delivered
  request whose answer was thrown away, which is worse than being a little late.
- Touching `client.py`'s shrink loop. Its behaviour narrows because the transport stops raising
  `ResponseTooLarge` for a failing status, which is where the decision belongs.

## Decisions

### The response path charges its elapsed time before the retry decision, not after

The connect path already does exactly this (`transport.py:246`): charge `monotonic() - started`,
then clamp the backoff to what is left. The response path gets the same two lines in the same
order, so that a slow round trip both shortens its own backoff and can exhaust the budget on the
spot.

*Alternative — charge after the body read:* wrong place. On a retry the body is never read (the
stream context exits and discards it), and on the give-up path the loop breaks immediately after,
so the charge would be recorded into a budget nothing reads again.

*Consequence, accepted:* an upstream that answers `429` slowly now gets fewer retries than one
that answers `429` instantly. That is the intended reading of a budget — the caller's tool call is
what is being bounded, not the upstream's attempt count — and `timeout_secs` is configurable for
an instance that is simply slow.

### A non-2xx body is read against the error-quoting bound, not the response ceiling

`_read_bounded` refuses at 25 MiB because that is what this server is willing to *decode into the
model's context*. A failing response is never decoded into anything: `raise_for_status` quotes at
most `message` out of it, and `errors.py` already drops any body over 64 KiB before parsing. So the
give-up path branches on `resp.is_success`: a success streams against the response ceiling exactly
as today, and a failure streams against the 64 KiB bound and stops there.

`_MAX_ERROR_BODY_BYTES` becomes public (`MAX_ERROR_BODY_BYTES`) and is imported by the transport,
so one constant governs both the streaming stop and the parse-time drop. This is also what makes
the comment at `transport.py:41` true — it has claimed since the ceiling was added that "the error
path has its own, much smaller bound", which today bounds only what is quoted, and above the
ceiling was never reached at all.

*What the read returns when the bound is crossed:* empty bytes, not a truncated prefix.
`_upstream_detail` already drops anything over that bound, and a truncated prefix can only ever
fail to parse as JSON, so `b""` is the existing meaning of "too big to quote" rather than a new
signal.

*Alternative — keep the ceiling and re-raise the ceiling error as a status error:* rejected. It
still allocates up to 25 MiB of a body nobody reads, and the status would be reported by a path
whose refusal type `search_entities` keys on.

### The classification seam widens to `httpx.RequestError`

One character of the `except` clause plus two dispatch arms. `HTTPStatusError` — the other half of
`httpx.HTTPError` — is deliberately left out: this server never asks httpx to raise it, and a
status is the status path's business. `RequestError` is precisely "this request did not produce a
response object I can hand back", which is what this handler is for.

The two new arms are dispatched **before** the delivery axis, because both are certainties on that
axis and the axis below them deals in maybes:

- `TooManyRedirects` — every hop was answered. The chain is the fault, not the network.
- `DecodingError` — the response arrived and its body contradicted its own `Content-Encoding`.

*Alternative — route both to `raise_transport_failed`:* it fixes the label and the context, which
is most of the harm, but its message says the request "may have been received" (both were) and
ends with a class-name diagnosis naming read, write, pool and protocol failures — none of which is
what happened. Two short raisers are cheaper than a message that hedges four ways.

### The redirect ceiling is five hops, set on the client

`max_redirects=5` on the `AsyncClient`, so it is enforced wherever a request is issued rather than
counted by hand in the loop. Five because the legitimate chains this server has met are one hop
(Aleph's canonical-host redirect; the profile `302`, which is not followed at all) and a reverse
proxy may add another — five leaves room for a deployment nobody has met while turning a loop from
21 requests into 6.

*Alternative — leave httpx's 20:* that is the library's default for a general-purpose client, not
a budget chosen by a server that retries. *Alternative — 1:* a single trailing-slash redirect
behind a proxy that also canonicalises the host would break a working deployment.

The refusal is not retried, for the same reason a TLS trust failure is not: the next attempt is
served the identical chain.

## Risks / Trade-offs

- **A deployment whose legitimate chain is longer than five hops starts failing.** → The refusal
  names the ceiling and says the chain did not terminate, so the diagnosis is in the message
  rather than in a log. The bound is one constant in one place.
- **An instance that answers a *successful* body over the ceiling with a non-2xx status header
  loses the shrink.** → It does, and that is the point: a `502` is not a paging problem. A `200`
  over the ceiling is shrunk exactly as before, which is every case the shrink was built for.
- **Charging the response path shortens retries against a slow upstream.** → Accepted above; the
  alternative is an unbounded tool call. The spec states the one-request overrun explicitly so the
  bound is not read as stricter than it is.
- **Two more refusal messages to keep consistent.** → Both go through `_reported`, the shared
  sanitise-and-label helper, so a new call site cannot copy half the pattern — the same guard
  `classify-transport-failures` added for the previous pair.

## Migration Plan

None. No configuration, signature or response shape changes; the observable delta is the text and
type of four refusals and the request count on three failure paths. Rollback is a revert.
