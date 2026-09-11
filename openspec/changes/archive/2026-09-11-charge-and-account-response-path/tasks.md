## 1. Charge the response path

- [x] 1.1 In `Transport.request`, charge `monotonic() - started` to the budget on the response
      path before the retry decision, so a slow round trip both shortens its own backoff and can
      exhaust the budget on the spot.
- [x] 1.2 Assert with a fake clock that a route answering a retryable status slowly stops
      retrying when the budget is spent, and that the call overruns by at most one request.
- [x] 1.3 Assert the fast case is unchanged: an instantly-answered retryable status still spends
      the full retry count. Already pinned by `test_gives_up_after_max_retries`, which asserts
      four attempts against a 503 — the assertion exists, so a second one would only restate it.

## 2. Report a failing status as the status

- [x] 2.1 Make `errors._MAX_ERROR_BODY_BYTES` public as `MAX_ERROR_BODY_BYTES`.
- [x] 2.2 Branch the give-up body read on `resp.is_success`: a success against
      `MAX_RESPONSE_BYTES` as today, a failure against `MAX_ERROR_BODY_BYTES`, returning empty
      bytes once that bound is crossed.
- [x] 2.3 Correct the comment at the top of `transport.py` that claims the error path already has
      its own smaller bound.
- [x] 2.4 Assert a `502` with an oversized body is refused as `unexpected HTTP 502`, is not a
      `ResponseTooLarge`, and costs one transport retry budget.
- [x] 2.5 Assert through `search_entities` that such a response is not re-asked with a smaller
      page — the 16-request measurement in the proposal.
- [x] 2.6 Assert a 2xx over the ceiling still raises the ceiling refusal and still shrinks, and
      that a failing body under 64 KiB still has its `message` quoted. The first half is the
      existing ceiling and shrink suites, left untouched and still green; the second is the
      closing assertion of the new bounded-read test.
- [x] 2.7 Rewrite the bounded-read test to assert on bytes consumed off the wire. Written against
      the refusal text it passed with the bound deleted — `_upstream_detail` drops an oversized
      body anyway, so the message cannot tell a bounded read from an unbounded one.

## 3. Widen the classification seam

- [x] 3.1 Widen the loop's `except` from `httpx.TransportError` to `httpx.RequestError`, keeping
      `ssl.SSLError` beside it.
- [x] 3.2 Add `raise_redirect_loop` and `raise_undecodable_body` to `errors.py`, both going
      through `_reported` so the transport text is sanitised and labelled.
- [x] 3.3 Dispatch `TooManyRedirects` and `DecodingError` ahead of the delivery axis; neither is
      retried.
- [x] 3.4 Widen the guard test that enumerates the family from `TransportError` to
      `RequestError`, so the partition stays verified rather than declared (15 → 18 cases).
- [x] 3.5 Assert a body contradicting its `Content-Encoding` is refused with call context and an
      untrusted label rather than the raw zlib sentence.

## 4. Bound the redirect chain

- [x] 4.1 Set `max_redirects` on the `AsyncClient` to a named constant of this server's own.
- [x] 4.2 Assert a redirect loop costs at most the ceiling plus the original request, is refused
      with call context, and says retrying will not help.
- [x] 4.3 Assert a chain within the bound is still followed to a successful answer, and that the
      read-only hook still fires on every hop.

## 5. Land

- [x] 5.1 Mutation-prove every new test: ten mutations, each caught, with a green control between
      every one and the tree green again afterwards. Two were checked for the reported symptom
      rather than merely for redness — the uncharged budget fails as `assert 4 == 3`, and the
      status-blind read fails on the missing `unexpected HTTP 502`.
- [x] 5.2 Run ruff, mypy, the full suite and `openspec validate --strict`.
- [x] 5.3 Re-measure the four symptoms through the shipped MCP path and record the before/after
      numbers: 4 requests / 47s → 3 / 33s; ceiling refusal → `unexpected HTTP 502`; 16 requests →
      4; 21 requests and a raw httpx sentence → 6 and a labelled refusal; a raw zlib sentence →
      a labelled refusal.
- [x] 5.4 Sync the delta into the published spec and archive the change.
- [x] 5.5 Close work-plan item 1 in `docs/implementation-notes.md`, renumber the plan, the section
      headings and every in-prose cross-reference.
- [x] 5.6 Delete `tests/test_zz_repro.py`.

## 6. Review round

Three reviewers on the PR diff. Findings fixed rather than parked, because each was about the
behaviour this change introduces.

- [x] 6.1 A refusal the budget ended now says so, names the attempts made and names
      `ALEPH_MCP_TIMEOUT_SECS`. Charging the response path made the budget able to end the loop,
      and measured, a `503` answered 30s into a 25s budget made one attempt and produced a message
      byte-identical to the four-attempt case.
- [x] 6.2 The `429` refusal stops asserting "retries are exhausted" when the clock rather than the
      count ended it — measured at three of four attempts, followed by advice to narrow a query
      that was never the problem.
- [x] 6.3 `_read_error_body` absorbs its own read failures, so a failing status outlives a body
      that cannot be decoded or read. Measured before: a `502` with a bad `Content-Encoding`
      answered with a Content-Encoding diagnosis and a `502` whose read died answered with a
      network diagnosis, the status in neither — the same trap this change exists to close.
- [x] 6.4 `raise_undecodable_body` stops excluding the network path and stops calling the fault
      deterministic. httpx's decoder raises on any chunk, so a mid-stream corruption and a broken
      encoder arrive identically; both claims were wrong for the first.
- [x] 6.5 The redirect refusal reports the hop count the client enforced, not the constant it was
      built with.
- [x] 6.6 `MAX_REDIRECTS` is pinned from both sides — a chain of exactly the bound succeeds, one
      hop more is refused, and the loop test's expected request count is a literal. Review
      measured the gap: with the expectation computed from the constant, `MAX_REDIRECTS` could be
      put back to httpx's 20 and the suite stayed green.
- [x] 6.7 Drop the assertion that a bad `Content-Encoding` "is not retried" — a `200` is not a
      retried status, so it held for a reason unrelated to the claim.
- [x] 6.8 Correct the module docstring (the budget is charged across sleep, connect *and* response
      time; two streaming bounds, not one), `raise_transport_failed`'s docstring (the fall-through
      family widened), and the enumeration test's "two of the fifteen".
- [x] 6.9 Name the `httpx.StreamError` exclusion in the walk's docstring: those are raised when
      this code uses a stream wrongly, not when an upstream misbehaves.
- [x] 6.10 Reset `started` after the response charge, so the handler below cannot double-count a
      round trip if a future arm falls through instead of raising.
- [x] 6.11 Add the two spec sentences the fixes make true, in the published spec and in this
      delta: what a budget-ended refusal must say, and that a failing status outlives an unreadable
      body.
- [x] 6.12 Re-prove: 19 mutations, every one caught, green control between each. 518 tests pass.
- [x] 6.13 Park what review found that this change did not introduce: the oversized error body
      dropped without saying so (its own entry) and the second way `transport.py:89` is stale.
