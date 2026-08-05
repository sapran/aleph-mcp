## 1. Confirm what is already covered

- [x] 1.1 Re-read `tests/test_tools.py` and `tests/test_resources.py` and record, per requirement in `specs/mcp-tool-surface/spec.md`, whether an MCP-layer assertion already exists. Do not assume: `tests/test_client.py` covers much of the same ground at the client layer, and those do not count for this spec.
      - R1 twelve names — **covered** (`test_tool_surface_is_exactly_the_read_set`).
      - R2 unprefixed — **not covered**.
      - R3 three resources — **not covered** (behaviour tested, the set is not).
      - R4 no document text — **not covered at MCP layer** (`test_client.py:42` only).
      - R5 over-window refused — **partial** (tool error asserted; no "no request issued", no negative paging).
      - R6 `searched` scope — **not covered at MCP layer** (`test_client.py:385,398,411` only).
      - R7 truncated expansion count — **not covered at MCP layer**.
      - R8 error translation — **partial** (bad `entity_id` and unknown schema resource covered; `get_entity_text` ranges not).
- [x] 1.2 Confirm `test_tool_surface_is_exactly_the_read_set` asserts equality against all twelve names and not a subset, and that `EXPECTED_TOOLS` matches the list in the spec exactly.
      - Confirmed: `assert names == EXPECTED_TOOLS` is set equality, and `EXPECTED_TOOLS` (`test_tools.py:12-25`) is exactly the twelve names in the spec.
- [x] 1.3 Note any requirement the current code cannot satisfy as written. If one exists, stop and amend the spec — this change must not modify `src/`.
      - **One found: R8.** `entity_id="e1\n"` passes `_check_entity_id` (`re.match` + `$` matches before a trailing newline) and then raises `httpx.InvalidURL`, which `@mcp.tool` does not translate because it only catches `ValueError`. `"e1\r"` is correctly rejected. `get_collection` shares the flaw via `_COLLECTION_ID.match`. Reproduced directly, not inferred.
      - Not a read-only bypass — httpx refuses to build the URL, so nothing is sent.
      - Resolution: spec amended with a "Known deviations" note under R8 rather than weakening the requirement; the case is recorded as a strict-xfail test so it fails loudly when fixed. Fix stays out of scope per §6.1.

## 2. Tool and resource surface (mocked)

- [x] 2.1 Extend the tool-enumeration test, or add one alongside it, asserting no registered tool name begins with `aleph_` or any other namespace prefix.
      - `test_tool_names_carry_no_namespace_prefix`. Also asserts the names do not all share one leading segment, which catches a prefix other than `aleph_`.
- [x] 2.2 Add a resource-surface enumeration test in `tests/test_resources.py` asserting exactly `aleph://collections`, `aleph://schemata` and the `aleph://schema/{name}` template are registered, each with mime type `application/json`. Existing tests exercise their behaviour but not the set.
      - `test_resource_surface_is_exactly_the_read_set`. Static resources and templates are listed separately (`list_resources` / `list_resource_templates`); the template does not appear in the static list.

## 3. Response-shape guarantees (mocked, MCP layer)

- [x] 3.1 `search_entities`: mock a hit carrying all five blob properties; assert none appear in the tool result and all five are listed sorted in `_omitted_properties`.
      - `test_search_hits_never_carry_document_text`. Also asserts a non-blob property (`fileName`) survives, so the test fails on over-stripping as well as under-stripping.
- [x] 3.2 `get_entity`: same assertion through the tool, not through `AlephClient`.
      - `test_get_entity_never_carries_document_text`.
- [x] 3.3 Assert a hit carrying no blob property has no `_omitted_properties` key at all.
      - `test_nothing_dropped_means_no_omitted_marker`.
- [x] 3.4 `search_entities`: assert `searched` reports `{"schemata": "Thing"}` when neither `schema` nor `schemata` is given, and `{"schema": ...}` when `schema` is given.
      - `test_search_reports_the_scope_it_used`.
- [x] 3.5 `search_entities`: assert a mocked total above 9999 produces the `_note`, and that a total below it does not.
      - `test_unreachable_total_is_marked_unenumerated` and `test_reachable_total_carries_no_note`.
- [x] 3.6 `expand_entity`: mock a property group whose `count` exceeds the returned entity count; assert the tool result preserves the true `count`.
      - `test_truncated_expansion_reports_true_degree` — one entity returned, `count` 4137.

## 4. Refusal and error translation (mocked)

- [x] 4.1 Confirm the existing `limit + offset > 9999` tool-error test also asserts no HTTP request was issued; add the assertion if absent.
      - It did not. Added `test_deep_pagination_never_reaches_the_wire`, which mocks the route and asserts `call_count == 0`. The original test is kept.
- [x] 4.2 Add tool-error coverage for negative `limit` and negative `offset` on `search_entities`.
      - `test_negative_paging_surfaces_as_tool_error`, parametrised, also asserting nothing reached the wire.
- [x] 4.3 Add tool-error coverage for `get_entity_text` with a negative `offset`, `limit=0`, and `limit=200001`.
      - `test_text_slice_bounds_surface_as_tool_error`, parametrised over all three, also asserting nothing reached the wire.
- [x] 4.4 Add resource-error coverage for `aleph://schema/{name}` with a name the mocked instance does not define.
      - Already covered by the existing `test_unknown_schema_resource_errors`; no new test. Verified it asserts on the resource, not the client.
- [x] 4.5 Record the R8 deviation found in 1.3 as a strict xfail so it fails loudly when fixed.
      - `test_trailing_newline_id_surfaces_as_tool_error`, `xfail(strict=True)`. Confirmed it fails for the right reason: the caller receives httpx's `Invalid non-printable ASCII character in URL` rather than the accepted id form.

## 5. Close out

- [x] 5.1 Run the mocked suite, ruff and mypy. Do not run `tests/live/` — nothing here needs it, and it requires credentials.
      - `pytest tests/ --ignore=tests/live`: **113 passed, 1 xfailed** (98 passed before this change; 16 tests added).
      - `ruff check`: all checks passed. `ruff format`: 1 file reformatted, now clean.
      - `mypy src tests`: 4 errors, all pre-existing on HEAD (`tests/live/test_live.py:33`, `tests/test_resources.py:45-46`) — verified by re-running against a stashed tree. No new error introduced.
      - `tests/live/` not run, as specified.
- [x] 5.2 Confirm `git diff --stat` touches only `tests/`, `openspec/` and `docs/`. Any hunk under `src/` means the baseline changed behaviour and must be split out.
      - `git diff --stat -- src/` is empty. Whole diff is `docs/implementation-notes.md`, `tests/test_resources.py`, `tests/test_tools.py`: **+219 / -0**, purely additive.
- [x] 5.3 `openspec validate baseline-mcp-tool-surface --strict`, then archive.
      - `validate --strict` passes. **Synced instead of archived**, at the user's direction: the delta is merged into `openspec/specs/mcp-tool-surface/spec.md` and this change stays active. Archive when the follow-ups below have been scoped.

## 6. Follow-up changes to raise separately — do not do them here

- [x] 6.1 Raise a change for the id-validation deviation in `docs/implementation-notes.md`: `_check_entity_id`/`_check_collection_id` use `re.match` with `$`, so `entity_id="e1\n"` passes validation and dies as an untranslated `httpx.InvalidURL`. This is a real violation of the error-translation requirement in this spec; recording it is in scope, fixing it is not.
      - Raised as `fix-id-validation-anchors`. Proposal written; also folds in the dot-segment id and the unvalidated `get_collection` numeric branch, which share the same cause. Removing the strict xfail added here is an explicit task in it.
- [x] 6.2 Raise a change baselining the `read-only-guard` capability, and settle the `get_collection?refresh=true` question inside it.
      - Raised as `baseline-read-only-guard`. Scoped wider than originally written, on the evidence from the adversarial review: it must also state the **unchecked query-string surface**, the redirect-hop and decoded-vs-raw rules, and the `http://` / `verify_tls: false` transport posture. `refresh=true` is named as a decision the change must settle, not defer again.
- [x] 6.3 Raise a change for the deferred cross-root OpenSpec reference to the `acordia` store, per `docs/implementation-notes.md`.
      - Raised as `declare-acordia-spec-reference`. Sequenced last of the three: it points at `mcp-tool-surface`, which must exist in `openspec/specs/` first — which the sync in 5.3 now provides.
