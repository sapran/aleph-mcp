## 1. Real-shaped fixtures

- [x] 1.1 Add `tests/shapes.py` with `raw_entity`, `raw_document`, `raw_search_payload` and
      `raw_model`, carrying the key set a live Aleph actually sends: nested `collection` with
      no top-level `collection_id`, null `caption`, and `links`/`writeable`/`mutable`/
      `shallow`/`latinized`/`bookmarked`/`created_at`/`updated_at`.
- [x] 1.2 Add `assert_slim_entity` and `assert_search_envelope`, encoding the reshaped
      contract once: the slim key set, no raw-only key, no document text inside
      `properties`, and every envelope result slim.
      - `searched` is an optional keyword on the envelope helper rather than a required key,
        because `entityset_items` and `match_entity` share `_slim_result` but do not report a
        search scope. The live shape test relies on that.
- [x] 1.3 Replace the inline `_entity` builder in `tests/test_client.py` and both hand-rolled
      copies of the FtM metadata payload (`tests/test_resources.py`, `tests/test_client.py`)
      with the shared builders.
      - All 59 existing client tests passed unchanged against the fuller payloads, so no
        assertion depended on the thin fixture shape.

## 2. `tests/test_tools.py` owns the MCP boundary only

- [x] 2.1 Keep the surface tests (`EXPECTED_TOOLS`, the `server` fixture, tool-set,
      no-mutation, no-prefix, instructions) and delete every response-shape test, which
      `tests/test_client.py` already proves.
- [x] 2.2 Replace the deliberate-duplication comment at the old `:142-147` with the layer
      contract, so the superseded rationale is answered rather than silently dropped.
- [x] 2.3 Add the `spied` fixture: patch all seventeen `AlephClient` methods with recorders
      *before* `build_server` constructs the client, so the patch reaches the tool closures.
- [x] 2.4 Add `FORWARDING_CASES` — every tool, every parameter, a value distinguishable from
      its default — and one parametrized test asserting `recorded == {tool: args}` and
      `result.data == {"_spy": tool}`.
- [x] 2.5 Add `ERROR_CASES` — one real refusal per tool — asserting `ToolError`, the message,
      and zero requests sent; `get_collection` is the single exception, needing one listing
      lookup before it can know the `foreign_id` is unknown, so it asserts the one call went
      to `/api/2/collections` and never to the detail route.
- [x] 2.6 Add a tripwire per table asserting its tool set equals `EXPECTED_TOOLS`, and delete
      the regex-scraping `TOOLS_CALLED_HERE` / `test_every_registered_tool_is_exercised_through_mcp`
      that they subsume.
- [x] 2.7 Add two end-to-end cases through respx: a search over `raw_entity` + `raw_document`,
      and `get_entity_text` over the page-child fallback — the first successful
      `get_entity_text` call through MCP.

## 3. Client-layer contracts

- [x] 3.1 Move down from the tool layer, against `AlephClient` directly: document-text
      stripping and its absence marker, the reachable-total case, negative search paging,
      text-slice bounds, trailing-whitespace ids, dot-only ids, dotted ids still accepted,
      and numeric-collection-id validation before interpolation.
      - `test_id_that_addresses_nothing_is_refused` now crosses the four-id corpus with all
        eleven id-taking methods (44 cases) instead of spot-checking `get_entity` and
        `entityset_items`.
      - `test_text_slice_bounds` replaces `test_get_entity_text_rejects_absurd_limit` and adds
        the `offset=-1` and `limit=0` bounds.
- [x] 3.2 Add `test_http_status_becomes_an_actionable_error` over 401/403/404/400/429/500,
      asserting the distinguishing phrase from `errors.py`. Nothing covered 401/404/400/500
      before.
      - Introduced a `no_sleep` fixture so the retrying statuses cost no wall-clock time, and
        migrated the two existing retry tests onto it rather than leaving two conventions.
- [x] 3.3 Close the remaining unreached client lines: scalar property value in
      `derive_caption` and in `slim_entity`, bare-list response wrapping, `highlight` sent
      when a query is present, negative `offset` on the listing cap, and an unparseable
      `Retry-After` falling back to backoff.
      - Also added `test_slim_entity_prefers_an_explicit_collection_id`: moving every fixture
        to the nested `collection` shape left the direct `collection_id` branch unreached, and
        the precedence between the two is worth pinning anyway.
- [x] 3.4 In `tests/test_readonly.py`, add `test_empty_path_is_normalised_to_root` for the
      base-path branch that maps a request to the prefix itself onto `/`. No other change: it
      is the sole owner of the guard contract.
- [x] 3.5 Retrofit `assert_slim_entity` / `assert_search_envelope` into the existing search,
      expand, expand_profile, similar, profile_similar, xref and entityset-items tests, in
      place of their ad-hoc `"bodyText" not in ...` checks.

## 4. Close out the mocked suite

- [x] 4.1 Run `pytest tests`, `ruff check .`, `ruff format` and `mypy`.
      - 250 passed (was 188). `ruff check` clean after removing a now-unused `typing.Any`
        import; `ruff format` reformatted three touched files; `mypy` clean, 7 source files.
- [x] 4.2 Re-run the line-level coverage tracer used to find the gaps and confirm none of
      `server.py` 73/165/177/189/239/251/287/301, `client.py` 103/134/311/421/422/791/801 or
      `readonly.py` 90 is still missed.
      - Confirmed. Remaining misses in `src/aleph_mcp/` are `def`/docstring lines plus
        `__main__.py`, which the suite does not drive.
- [x] 4.3 Prove the forwarding table is load-bearing: temporarily drop `limit=limit` from
      `server.py`'s `expand_entity` call and confirm exactly one forwarding case fails.
      - 1 failed, 16 passed, with the diff showing the missing `'limit': 9`. `server.py`
        restored; `git diff -- src/` is empty.
- [x] 4.4 Update the two test counts in the README "Develop" section, and the tripwire
      paragraph, which named the test deleted in 2.6.

## 5. Live suite (needs credentials — separate from tasks 1–4)

- [x] 5.1 Rewrite the `ids` fixture so discovery does not depend on which collection sorts
      first: iterate every readable collection for an entityset, fall back to
      `list_entitysets(set_type="profile")` for a profile id, and ask for `schema="Pages"`
      directly for a document id.
- [x] 5.2 Add `ALEPH_MCP_LIVE_STRICT`: a single `_no_fixture_data` helper that fails instead
      of skipping when the variable is `1`. Route `need()` and the three standalone skips
      through it, and document the variable in the module docstring beside
      `ALEPH_MCP_LIVE_TESTS`.
- [x] 5.3 Add `test_live_responses_match_the_shape_the_mocked_suite_asserts`, running real
      `search_entities` and `entityset_items` payloads through the same
      `assert_search_envelope` that guards the mocked suite.
- [x] 5.4 Leave the `xref_results` live case as an empty-result round trip: the instance has
      no computed cross-reference and computing one needs a write-scoped key this server
      refuses by design.
- [x] 5.5 Run the live suite with `ALEPH_MCP_LIVE_STRICT=1` and confirm **0 skipped**, then
      again without it to confirm a contributor with a thinner instance is not broken.
      - **31 passed, 0 skipped** strict (was 23 passed / 7 skipped); 31 passed non-strict. All
        four profile tools, both entityset tools and `get_entity_text` now run against real
        data.
