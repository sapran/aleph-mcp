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
