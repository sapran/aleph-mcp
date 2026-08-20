## Why

**This changes no observable behaviour.** Nothing in `src/aleph_mcp/` is touched: the
seventeen tool names, their arguments, their response keys and every refusal are exactly
what `baseline-mcp-tool-surface` and `extend-profile-tool-surface` already shipped. This is
a change to how those contracts are *proven*, and it is worth writing down because the
existing arrangement was actively hiding gaps.

`tests/test_tools.py` had grown to 637 lines whose bulk re-asserted response shapes that
`tests/test_client.py` already proves against `AlephClient`. The duplication was
deliberate, and the file said so at `tests/test_tools.py:142-147`: the contract is
published at the MCP layer, so a refactor registering a tool that bypassed the slimming
path would leave the client tests green while breaking every consumer. Archived task 3.4 of
`2026-08-05-fix-id-validation-anchors` followed the same reasoning, moving a
client-layer regression to the tool layer "matching the convention set in
`baseline-mcp-tool-surface`".

That defence did not hold up when measured. Because each tool was proven by a
hand-written case, coverage went exactly as far as someone had bothered to write:

- Eight of the seventeen `except ValueError: raise ToolError` lines in `server.py` never
  executed (73, 165, 177, 189, 239, 251, 287, 301).
- `expand_profile` and `get_entity_text` had no *successful* call through MCP at all —
  only refusals — so fifteen tools were covered, not seventeen.
- Eight tools were only ever called with their default arguments, so a dropped or renamed
  keyword in a tool's forwarding call was invisible.
- Seven client lines and one `readonly.py` line were unreached (`client.py` 103, 134, 311,
  421, 422, 791, 801; `readonly.py` 90), including the whole 401/404/400/500 status-mapping
  table in `errors.py`, which no test anywhere exercised.

Separately, no mocked fixture reproduced the key set a real Aleph sends. Measured against a
live instance, a search hit carries `collection, created_at, id, latinized, links, mutable,
properties, schema, score, shallow, updated_at, writeable` and no `caption`. The suite's
builders carried a flat `collection_id` and a populated `caption`, so a slimmer that started
leaking `links` or `writeable` could not have failed any test — the fixtures never
contained those keys.

The live suite reported 23 passed / 7 skipped and read as coverage of a thin instance. It
was not: the instance held the profile, the entityset and the documents all seven skipped
cases needed. The `ids` fixture simply could not find them. `collection_id` came from
`list_collections(limit=1)`, which returned collection `2`, while the only entityset lived
in collection `1`; `profile_id` was read off the first 50 `Thing` hits, which were
collection-2 rows with no profile; and `document_id` required `_omitted_properties` among
those same hits, which live `Pages` rows never carry because Aleph does not return
`indexText`/`bodyText` in search hits.

## What Changes

- **Supersede the deliberate-duplication rationale** at `tests/test_tools.py:142-147`, and
  with it the convention archived task 3.4 of `2026-08-05-fix-id-validation-anchors`
  followed. The bug that rationale defended against — a tool wired to the wrong client
  method, or dropping an argument — is now caught for **all seventeen tools and every one
  of their parameters** by two parametrized tables, instead of for fifteen tools at
  whatever argument coverage each hand-written case happened to have:
  - `FORWARDING_CASES` patches every `AlephClient` method with a recorder, calls each tool
    through `MCPClient`, and asserts the recorded kwargs equal the call arguments exactly
    and that the tool returned the client's payload unmodified (a `_spy` sentinel, because
    an empty dict cannot distinguish "returned the payload" from "returned nothing").
  - `ERROR_CASES` drives one real refusal per tool and asserts it reaches the caller as a
    `ToolError` carrying the client's message, having sent nothing to Aleph.
  - Each table has a tripwire asserting its keys equal `EXPECTED_TOOLS`, which subsumes and
    replaces the regex-scraping `test_every_registered_tool_is_exercised_through_mcp`.
  - Two end-to-end cases stay on the real stack, because a spy proves wiring but not that
    the stack composes. One of them is the first successful `get_entity_text` call through
    MCP.
- **Add `tests/shapes.py`**: payload builders in the shape Aleph really serialises (nested
  `collection`, null `caption`, and the housekeeping keys the slimmer must drop), plus
  `assert_slim_entity` / `assert_search_envelope`, which encode the reshaped contract once.
  It replaces the inline `_entity` and `_doc_entity` builders and both hand-rolled copies of
  the FtM metadata payload.
- **Move the assertions that existed only at the MCP layer down to `tests/test_client.py`**,
  against `AlephClient` directly, and widen them: the id corpus is now crossed with all
  eleven id-taking methods rather than spot-checked on two, and the HTTP status table is
  covered for the first time.
- **Fix live discovery** so the suite finds the data the instance holds: ask every readable
  collection for its entitysets, fall back to `list_entitysets(set_type="profile")` for a
  profile id (a profile *is* an entityset and its id is the profile id), and ask Aleph for
  `schema="Pages"` instead of filtering general hits for text properties.
- **Add `ALEPH_MCP_LIVE_STRICT`.** Set to `1`, a case that would skip for missing fixture
  data fails instead. Without it, a run whose discovery quietly stopped working is
  indistinguishable from a green one — which is exactly how the seven false skips survived.
- **Add one live shape test** that runs real `search_entities` and `entityset_items`
  payloads through the same `assert_search_envelope` the mocked suite uses, so a field the
  slimmer starts leaking fails live rather than passing everywhere.

**Decision: spies for wiring, respx for composition.** Monkeypatching the seventeen client
methods proves argument forwarding and payload pass-through for every tool in one table.
Doing the same with per-tool respx mocks would require each case to assert a response
shape — reintroducing the duplication this change removes. The two end-to-end cases keep a
real path through the stack.

**Left alone deliberately.** `total_type` is carried by the new search-payload builder but
unused: live search returns `total: 10000, total_type: "gte"` while `client.py:431` infers
the same floor from `total_count > MAX_PAGE`, and the two agree at every observed value.
Keying the UNENUMERATED note off `total_type` would be a client behaviour change and belongs
in its own change. The live `xref_results` case also stays an empty-result round trip: the
instance has no computed cross-reference and running one needs a write-scoped key this
server refuses by design.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No tool name, argument, response key or refusal changes, so there is no spec delta;
`.openspec.yaml` sets `skip_specs: true`.

## Impact

- **Modified files:** `tests/test_tools.py` (rewritten as the MCP-wiring suite),
  `tests/test_client.py`, `tests/test_resources.py`, `tests/test_readonly.py`,
  `tests/live/test_live.py`, `README.md` (test counts and the tripwire paragraph, which
  named a test this change deletes).
- **New file:** `tests/shapes.py`.
- **Modified code:** none. `git diff -- src/` is empty, `readonly.py` included.
- **Result:** mocked suite 188 → 250 tests, all green. Live suite 23 passed / 7 skipped →
  **31 passed / 0 skipped** under `ALEPH_MCP_LIVE_STRICT=1`, and still 31 passed without
  it. Every line listed in the Why above is now executed; the only lines the tracer still
  reports as unreached in `src/aleph_mcp/` are `def`/docstring lines and `__main__.py`,
  which the suite does not drive.
- **Risk:** live discovery depends on the instance keeping its profile and its `Pages`
  entities. If either is removed, `ALEPH_MCP_LIVE_STRICT=1` fails loudly and a plain run
  degrades to a skip naming the missing data. That is the intended behaviour. The live suite
  stays read-only and seeds nothing: fixture data is a property of the instance, not of the
  suite, per the read-only invariant in `openspec/config.yaml`.
