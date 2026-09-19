## Why

Work-plan item 1 in `docs/implementation-notes.md`: the response half of `Transport.request` is
neither charged to the retry budget nor accounted for when it fails. One seam, four symptoms, all
re-measured on this tree (`develop @ 37931ea`) before proposing:

- **A slow response is free.** A route answering `503` after ten seconds, against a 25-second
  `timeout_secs`, cost **4 requests and 47 seconds of wall clock**. Only the 7 seconds of backoff
  were charged: `transport.py:246` charges the connect path's elapsed time, and the same one-line
  charge was never extended to the response path.
- **A failing status with a big body is reported as a size problem.** `_read_bounded` runs before
  `raise_for_status` and never looks at `resp.status_code`, so a `502` carrying a >25 MiB body
  raises `TooLargeToolError` and the `502` is discarded. Measured: a plain `502` costs 4 requests
  and says "unexpected HTTP 502"; a `502` with an oversized body costs **16 requests** through
  `search_entities` — the shrink loop re-asks four times, each paying four transport retries
  because `502` is in `_RETRY_STATUS` — and tells the model to *narrow its query*, never that the
  instance is failing.
- **A redirect loop costs 21 upstream requests and reports httpx's own sentence.** Driven through
  the shipped MCP path, an instance answering `302` with a `Location` back to the same allowlisted
  path produced **21 requests for one tool call** and
  `Error calling tool 'list_collections': Exceeded maximum allowed redirects.` — no call context,
  no untrusted label, nothing charged. The 20-hop bound is httpx's default, not a budget this
  server chose.
- **A malformed compressed body reaches the model as a raw zlib sentence.** A `200` carrying
  `Content-Encoding: gzip` and a body that is not gzip produced
  `Error calling tool 'list_collections': Error -3 while decompressing data: incorrect header check`.

The last two escape the seam `classify-transport-failures` hardened because `httpx.TooManyRedirects`
and `httpx.DecodingError` are siblings of `httpx.TransportError` under `httpx.RequestError`, and
that spec says so in as many words rather than claiming a guarantee it did not hold. This change
makes the guarantee true and then widens the sentence.

## What Changes

- The response path charges its elapsed time to the one wall-clock budget, before the retry
  decision, so a slow 5xx round trip cannot be repeated `max_retries` times outside the budget.
- A non-2xx response is no longer read against the 25 MiB ceiling. It is read against the much
  smaller bound the error path already applies to what it quotes, and is reported as its status.
  **BREAKING** for one refusal message: an oversized `502` now says "unexpected HTTP 502" instead
  of the ceiling refusal, and no longer raises `ResponseTooLarge`, so `search_entities` stops
  re-asking a failing upstream with smaller pages (16 requests → 4).
- The classification seam widens from `httpx.TransportError` to `httpx.RequestError`, so every
  sibling — including one nobody has classified — is refused through this server's own error path
  with context, sanitising and the untrusted label.
- `TooManyRedirects` and `DecodingError` each get a refusal naming what actually happened, and
  neither is retried.
- The redirect chain is bounded by this server rather than by httpx's default, so a redirect loop
  costs a number of upstream requests this project chose.
- No tool signature, argument or successful reply shape changes.

## Capabilities

### New Capabilities

None. Every requirement below belongs to the existing tool-surface contract.

### Modified Capabilities

- `mcp-tool-surface`: four requirement changes.
  - *Every transport failure is refused through this server's own error path* — the family widens
    from `httpx.TransportError` to `httpx.RequestError`, and the paragraph parking
    `TooManyRedirects` and `DecodingError` as out of reach is removed because it stops being true.
  - *An oversized search page is reduced, not discarded* — the reduction applies to a successful
    response only; a failing status is reported as the status and is not re-asked smaller.
  - New: *One tool call spends one wall-clock budget* — every attempt's elapsed time is charged,
    whichever half of the request spent it.
  - New: *A redirect chain is bounded by this server* — the hop ceiling is this project's, the
    loop is refused with context, and it is not retried.

## Impact

- `src/aleph_mcp/transport.py` — the budget charge on the response path, the status-aware body
  read, the widened `except`, the redirect bound, and the comment at the top that currently
  describes an error-path bound the code does not enforce.
- `src/aleph_mcp/errors.py` — two new refusals; the error-body bound becomes importable because
  the transport now enforces it while streaming rather than after the fact.
- `src/aleph_mcp/client.py` — no code change expected; the shrink loop's behaviour narrows by way
  of what the transport raises.
- `tests/test_transport.py` — the guard test that enumerates the classified family, plus the new
  cases.
- No dependency, configuration or tool-surface change.
