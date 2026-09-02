## Why

A live ACORDIA run against a ~4.5M-entity Aleph collection lost a whole result set to this
error:

```
search_entities: upstream response is 26214540 bytes, over the 26214400-byte ceiling
```

140 bytes over a 25 MiB ceiling, and every row was discarded. The caller wanted counts, and
any partial page would have served. A result window that large is a paging problem, not an
unanswerable query — the server already knows how to ask for fewer rows, so refusing the call
outright spends a turn to teach the caller something the server could have done itself.

The ceiling itself is not in question: it bounds the allocation while the body streams, and it
is the only defence against a body too large to decode into the model's context. What is wrong
is the response to crossing it.

## What Changes

- `search_entities` re-issues its query with a smaller `limit` when the upstream body crosses
  the response ceiling, up to a bounded number of attempts, instead of failing the call.
- A response served that way carries `truncated: true` and `continue_from_offset`, and reports
  `limit` and `offset` as the page actually served. `total` is unaffected, so paging still
  works. Both markers are withheld when the reduced page served no rows, because resuming at
  the offset just used would repeat the identical request.
- The reduction is bounded twice over: by a hop count, and by one deadline across the whole
  loop. A shrink issues a fresh request with its own retry budget, so the hop count alone
  would multiply that budget — and a body made large by its facet block, rather than by its
  rows, is not reduced by a smaller page at all and would spend every hop regardless.
- A page of one that is still oversized, and a facet-only search (`limit=0`), keep raising the
  ceiling error: no page size reduces either, and the existing message already tells the caller
  to narrow the query.
- The ceiling refusal becomes catchable by type (`ResponseTooLarge`) rather than only by
  message text, so the shrink loop can recognise it without matching prose. The message is
  unchanged.
- Not a behaviour change, stated to bound the blast radius: every existing validation in
  `search_entities` runs ahead of the loop untouched, and shrinking only ever *lowers* `limit`,
  so an oversized page cannot bypass the `limit + offset > 9999` refusal.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `mcp-tool-surface`: adds one requirement. The capability's stated purpose covers "what a
  caller may rely on in their responses, and how they fail", and this change adds two response
  keys (`truncated`, `continue_from_offset`) and converts a failure into a partial success —
  both squarely inside that sentence, which is what makes this a spec change rather than an
  implementation detail. No existing requirement is falsified: the `limit + offset > 9999`
  refusal, the unenumerated-tail `_note` and the `searched` scope disclosure all keep holding
  exactly as written.

## Impact

- `src/aleph_mcp/client.py` — `search_entities` gains the shrink loop and two constants;
  parameter building moves into a closure so it can be rebuilt per page size.
- `src/aleph_mcp/errors.py` — `raise_too_large` raises a typed subclass carrying `size` and
  `limit`. Message text unchanged, so existing tests matching on it keep passing.
- `src/aleph_mcp/server.py` — the `search_entities` docstring names the two new keys, because a
  key the model cannot discover is a key it will not use.
- `tests/shapes.py` — `assert_search_envelope` rejects any unexpected response key, so the two
  new ones must be admitted or ~20 existing search tests fail.
- Callers: additive only. A caller that ignores `truncated` sees a short page where it
  previously saw an error.
- Aleph: a shrunk call issues up to `MAX_SEARCH_SHRINKS` extra requests, but only on a page
  that would otherwise have failed outright.
