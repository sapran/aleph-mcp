## 1. Read-only allowlist

- [x] 1.1 Add five GET pairs to `_ALLOWED` in `src/aleph_mcp/readonly.py`: `/api/2/profiles/<id>`, `/api/2/profiles/<id>/expand`, `/api/2/profiles/<id>/similar`, `/api/2/profiles/<id>/tags`, `/api/2/entitysets/<id>`, reusing `_ENTITY_ID` and keeping the resource-grouped ordering
- [x] 1.2 Document at the pattern definition why the method pin is load-bearing for `POST /api/2/profiles/_pairwise` and why `_ENTITY_ID` must not be narrowed to hex

## 2. Client methods

- [x] 2.1 Add a `# -- profiles --` section after entity search with `get_profile`, `profile_tags`, `profile_similar`, `expand_profile`
- [x] 2.2 Pass `get_profile`'s `merged` through `slim_entity`; project the profile to id/type/label/summary/collection_id/updated_at/entities/merged
- [x] 2.3 Reuse `similar_entities`' reshape for `profile_similar` and `expand_entity`'s cap guard and grouping for `expand_profile`
- [x] 2.4 Add `_slim_entityset(s, *, full=False)` beside `_slim_collection` and refactor `list_entitysets` onto it
- [x] 2.5 Add `get_entityset` using `full=True`, setting `_note` when Aleph redirected to the profile view

## 3. Tool registrations and instructions

- [x] 3.1 Register `get_profile`, `profile_tags`, `profile_similar`, `expand_profile` after `match_entity`, and `get_entityset` between `list_entitysets` and `entityset_items`
- [x] 3.2 Docstring `get_profile` with what a profile is and that `profile_id` arrives on entity results; name the 200-per-property ceiling on `expand_profile`
- [x] 3.3 Replace the `INSTRUCTIONS` claim that `q` carries a fuzzy boost with the true semantics: not fuzzy, 66% `minimum_should_match`, `match_entity` for name lookup
- [x] 3.4 Extend `INSTRUCTIONS` step 4 to route to the profile cluster when a result carries `profile_id`

## 4. Tests

- [x] 4.1 Grow `EXPECTED_TOOLS` in `tests/test_tools.py` to the seventeen names
- [x] 4.2 Add the five new paths to the positive allowlist parametrize in `tests/test_readonly.py`
- [x] 4.3 Add `test_pairwise_judgement_is_blocked`: GET allowed, POST refused, so the refusal is attributable to the method pin
- [x] 4.4 Add client tests: `expand_profile` cap refusal, `merged` slimming and `_omitted_properties`, `latinized` dropped, `profile_tags` passthrough, `profile_similar` shape, `get_entityset` `_note` and detail fields
- [x] 4.5 Add MCP-layer tests: id validation on `get_profile`, one route-reaching test per new tool, `expand_profile` cap refusal at the tool boundary
- [x] 4.6 Add a live test that discovers a `profile_id` from a search hit, exercises all four profile tools plus the entityset redirect, and skips when the instance has no profiles

## 5. Documentation

- [x] 5.1 Add the five rows to the README Surface table and change "twelve tools" to "seventeen"
- [x] 5.2 Fix the same false fuzzy claim in the README's "No raw Elasticsearch DSL" bullet

## 6. Verification

- [x] 6.1 `uv run pytest` — full suite green with the grown tool set
- [x] 6.2 `uv run ruff check .` and `uv run mypy` clean
- [x] 6.3 Guard check: `GET /api/2/profiles/<id>/expand` allowed, `POST /api/2/profiles/_pairwise` and `POST /api/2/profiles/<id>` refused
- [x] 6.4 Live end-to-end against the local Aleph (`~/git/aleph`, creds in `.local-credentials`): created a profile fixture via the raw API, then read it back through the tools. Discovery from a search hit, `get_profile` (2 constituents merged, caption and properties correct), `profile_tags` (3), `profile_similar` (0), `expand_profile` (`emailsReceived`/`emailsSent`), `get_entityset` reporting the profile, and `POST /_pairwise` refused before the network. Live suite: 9 passed, 1 skipped (no `Pages` documents in the sample data — unrelated).
- [x] 6.5 Live probe found a second, stronger instance of the load-bearing method pin: `/api/2/entitysets/<id>` is allowlisted for GET and Aleph registers DELETE, POST and PUT on that identical path (`entitysets_api.py:144,181`). Documented at the allowlist, asserted by `test_entityset_detail_writes_are_blocked_on_method_alone`, and recorded in the `read-only-guard` requirement.
- [x] 6.6 **Defect caught only by the live run, now fixed.** `get_entityset`'s profile path was dead code: Aleph builds the `302` `Location` from its configured public UI URL (observed `localhost:8080` for an API on `:5000`), so following it left the API, lost the stripped `Authorization` header, and returned `403` for a readable resource. The tool now disables redirect-following for that request and treats the `302` as the answer. The mocked test that "passed" had returned a `200` and never exercised a redirect; it now asserts the `302` is read and the target is never called.
