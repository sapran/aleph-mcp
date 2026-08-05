## Why

This is a **baseline of already-shipped behaviour.** The guard shipped across `f51c0f7` ("feat: enforce read-only Aleph access at the HTTP layer") and `a062bab` ("fix: pin the read-only guard to the configured host and base path"), with a live assertion added in `e534a6b`. It is the strongest claim this project makes and the only one whose failure mode is an unauthorised write into someone else's live investigation — and it has no spec.

`baseline-mcp-tool-surface` deliberately left it out, because the allowlist warrants its own review bar rather than riding along on a tool-surface change.

Adversarial probing confirmed the guarantee holds. Every attempt was refused: a three-hop redirect chain ending at `POST .../reingest` (hook fired on all three hops, write route never called); a 307 redirect replaying a `POST /api/2/match` body into an ingest endpoint; a cross-host redirect to an attacker host (blocked, and the `Authorization` header was never emitted); and six path-traversal and percent-encoding variants (`%2F`, `%2e%2e`, `%00`, `;`, `//`, mixed-case), all blocked. The decoded-vs-raw asymmetry noted in `docs/implementation-notes.md` fails closed by construction: decoding can only add path separators, which makes a `fullmatch` against a fixed segment count stricter, never looser.

So the reason to specify it is not doubt. It is that **the guarantee as stated is broader than the guarantee as enforced**, and the gap is currently undocumented:

- The allowlist matches on `(method, path)` only. **Query strings are not checked at all.** `?refresh=true`, `?sync=true` and `?_method=DELETE` all pass. None of them mutate in Aleph today, but nothing in the design says they cannot, and the guard is not what is stopping them.
- `get_collection` sends `refresh=true` unconditionally on its numeric branch, asking Aleph to recompute collection statistics. It creates, changes and deletes nothing — but it is the only request in the package that asks the server to do work beyond answering, and it is the sentence an external audit will stop at.
- `config.py` accepts `http://` hosts and a `verify_tls: false` setting. Neither breaks read-only — an attacker in that position still cannot make this server write — but the API key can travel in clear and responses can be forged. "Read-only" and "trustworthy data" are different guarantees and only the first is enforced.

## What Changes

No behavioural change is proposed. This writes down the guarantee, states its real boundary, and adds the tests that hold the boundary in place.

- Add capability `read-only-guard`.
- Specify the guarantee as **what is refused**: any request whose method and path are not in the allowlist, on any redirect hop, regardless of API key permission — and specify that widening the allowlist tuple is the only mechanism that can widen the surface.
- Specify the host and base-path pin, including the reason it exists: an Aleph instance can redirect, and a `POST /api/2/match` body would otherwise be replayed to the redirect target.
- Specify that the guard runs on **every** redirect hop, not only the initial request. This is a property of where the hook is installed and would be silently lost by a refactor that moved it.
- Specify the decoded-vs-raw matching rule and why it fails closed, including the condition that would invalidate it: if the id charset is ever widened to include `%`, the hook must match `raw_path` instead.
- **State the query-string gap explicitly** rather than leaving it inherited, and decide whether to close it. Options to weigh in design: leave it specified-but-open; add a deny list for known side-effecting parameters; or require an allowlist entry to declare its permitted parameters.
- Settle `refresh=true`: either specify it as an accepted, named exception to "asks the server only to answer", or drop it and take the staleness.
- Record the transport-security posture — `http://` and `verify_tls: false` are permitted and are out of scope for this guarantee — so it is a stated position rather than an oversight.
- Add tests for the redirect-hop, 307-body-replay, cross-host-key-leak and encoding cases. These were verified by hand during review and none of them is currently in the suite.

## Capabilities

### New Capabilities

- `read-only-guard`: what this server refuses to send, on every hop, and the boundary of that guarantee.

### Modified Capabilities

None.

## Impact

- **New files:** `openspec/specs/read-only-guard/spec.md` (on archive); new cases in `tests/test_readonly.py`.
- **Modified code:** none, unless the design decides to close the query-string gap — in which case that edit is the whole of the change and gets reviewed as a security change.
- **Interaction with other changes:** independent of `fix-id-validation-anchors`, which touches validation rather than the guard. Neither may widen the allowlist.
- **Verification:** mocked suite for the guard itself, since it refuses client-side before the wire. `tests/live/` already covers the live assertion and is not extended here.
