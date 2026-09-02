## 1. Make the ceiling refusal catchable by type

- [x] 1.1 Add `ResponseTooLarge` marker with `size`/`limit` class attributes, plus
  `TooLargeToolError(ToolError, ResponseTooLarge)` and
  `TooLargeResourceError(ResourceError, ResponseTooLarge)` in `src/aleph_mcp/errors.py`
- [x] 1.2 Rewrite `raise_too_large` to raise the typed class and set `size`/`limit`, leaving the
  message text byte-identical so the existing `match=r"over the .* ceiling"` tests still pass

## 2. Shrink the page in search_entities

- [x] 2.1 Add `MAX_SEARCH_SHRINKS = 3` and `_SHRINK_MARGIN = 0.8` to `src/aleph_mcp/client.py`
  with the rationale for each, and extend the `.errors` import with `ResponseTooLarge`
- [x] 2.2 Turn `search_entities`' parameter block into a `page_params(page)` closure so the
  query can be rebuilt at a new page size, leaving every prior validation untouched
- [x] 2.3 Add the shrink loop: proportional first aim, halve after, strictly decreasing, floor
  at one row, re-raise at the floor or when the attempts are spent

## 3. Report the truncation

- [x] 3.1 Set `truncated`, `continue_from_offset` and the served `limit` when the page was
  reduced
- [x] 3.2 Compose the `_note` from a list so the truncation statement and the unenumerated-tail
  statement coexist instead of overwriting each other
- [x] 3.3 Admit `truncated` and `continue_from_offset` in `ENVELOPE_OPTIONAL` in
  `tests/shapes.py`, which otherwise rejects them across ~20 existing search tests
- [x] 3.4 Name both keys in the `search_entities` docstring in `src/aleph_mcp/server.py`

## 4. Verify

- [x] 4.1 Add tests: an oversized page is shrunk and marked; a page that fits carries no marker;
  a page of one is refused unre-issued; a facet-only search is refused; both notes coexist
- [x] 4.2 Full gate — `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy`
- [x] 4.3 Mutation proof: `never-shrink`, `marker-dropped`, `resume-offset-wrong` must each go
  RED, behind a control run proving the harness imports the mutated copy
- [x] 4.4 Behavioural check outside pytest printing `truncated`, `limit`,
  `continue_from_offset` and the first row of a shrunk page
- [x] 4.5 Best-effort live check against the real instance; if no page size trips the ceiling,
  record that plainly rather than claiming a live check that did not happen
