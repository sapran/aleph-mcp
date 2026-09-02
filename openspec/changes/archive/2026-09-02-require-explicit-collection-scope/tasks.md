## 1. Collection resolution in the client

- [ ] 1.1 Extract the numeric-vs-foreign-id branch out of `get_collection` into
      `_resolve_collection_id(value)`, returning a validated numeric id string. Numeric-looking
      values go through `_check_collection_id`; anything else is looked up by
      `filter:foreign_id` and raises the existing "no collection with foreign_id" error naming
      `list_collections`. Re-point `get_collection` at it so there is one resolver.
- [ ] 1.2 Add a process-lifetime cache keyed on the foreign id holding its numeric id, beside
      the existing `_model` cache. A collection's numeric id never changes, so the cache needs
      no invalidation.
- [ ] 1.3 Add `_resolve_collection_scope(collection)` returning either the literal `"*"` or a
      list of numeric ids, accepting a string or a list of strings and resolving each element
      through 1.1.

## 2. Require the scope on search_entities

- [ ] 2.1 Add a required `collection: str | list[str]` first parameter to
      `AlephClient.search_entities` and to the `search_entities` tool in `server.py`.
- [ ] 2.2 Refuse `filters` carrying a `collection_id` key, with a `ValueError` naming the
      `collection` argument and the offending value. Leave every other `filters` key untouched.
- [ ] 2.3 Resolve the scope ahead of the paging validations, and append one
      `filter:collection_id` parameter per resolved id inside `page_params` so the shrink loop
      rebuilds them unchanged.
- [ ] 2.4 Report the resolved scope as `searched["collection"]` — the id list, or `"*"`.
- [ ] 2.5 Add a `_note` line for a `"*"` search stating that the result spans every readable
      collection, composing with the existing truncation and unenumerated notes rather than
      overwriting them.

## 3. One vocabulary across the surface

- [ ] 3.1 Rename `collection_ids` to `collection` on `match_entity`, make it required, and route
      it through `_resolve_collection_scope`. `"*"` omits the parameter, which is Aleph's
      all-collections behaviour for match.
- [ ] 3.2 Rename `collection_id` to `collection` on `list_entitysets` and `xref_results`, routing
      both through `_resolve_collection_id` so a foreign_id works where only a numeric id did.
- [ ] 3.3 Update all four tool docstrings in `server.py` to name `collection`, state that it
      accepts a numeric id or a foreign_id, and state `"*"` where it applies.

## 4. State the rule where the model reads it first

- [ ] 4.1 In `server.py` `INSTRUCTIONS`, make the collection scope step 1 of the working method:
      every search names its collection, `"*"` is the only way to search all of them, and the
      same word works on every tool. The instructions block ships on every mount, ahead of any
      tool description, so this is the earliest place the rule can be stated.
- [ ] 4.2 Add the `searched.collection` key to the list of response keys the instructions
      describe, so a caller knows the scope is verifiable rather than assumed.

## 5. Tests, mocked suite only

- [ ] 5.1 Admit `searched.collection` in `assert_search_envelope` in `tests/shapes.py`, then pass
      a scope in every existing search call across `tests/test_tools.py` and
      `tests/test_client.py`. Record how many call sites needed one — a suite that still passed
      untouched would prove the parameter is not required.
- [ ] 5.2 Assert an omitted `collection` fails and reaches no wire, driven through the MCP client
      so the failure is the tool-signature refusal rather than an internal check.
- [ ] 5.3 Assert a numeric id emits exactly one `filter:collection_id`, and that a list emits one
      per id.
- [ ] 5.4 Assert `"*"` emits no collection filter, reports `"*"` in `searched.collection`, and
      carries the spanning `_note`.
- [ ] 5.5 Assert a foreign_id resolves via `filter:foreign_id` and that the resolution is cached:
      two searches on the same foreign id issue one lookup, asserted on `call_count`.
- [ ] 5.6 Assert an unresolvable foreign_id raises a tool error naming `list_collections`, and
      that no entity search is issued.
- [ ] 5.7 Assert `filters={"collection_id": …}` raises a tool error naming `collection` and
      reaches no wire.
- [ ] 5.8 Assert the renamed parameters: no registered tool declares `collection_id` or
      `collection_ids`, read off the MCP tool schemas rather than the Python signatures.
- [ ] 5.9 Assert a `"*"` search inside an unenumerated result set carries both notes, matching the
      composition rule the truncation notes already follow.
- [ ] 5.10 Mutation-prove 5.2, 5.4 and 5.7: make `collection` optional, drop the `"*"` note, and
      merge `filters.collection_id` instead of refusing it; confirm each test fails with the
      symptom it names, then restore.

## 6. Verify

- [ ] 6.1 `uv run pytest` — full mocked suite green, with the count of tests touched by 5.1.
- [ ] 6.2 `uv run mypy src tests` and `uv run ruff check .` clean.
- [ ] 6.3 `uv run python` probe through an in-memory `fastmcp` client reproducing the failing run's
      four calls: `collection="874"` now succeeds and is scoped, and the bare unscoped call now
      fails. This is the acceptance criterion for the whole change.
- [ ] 6.4 `openspec validate require-explicit-collection-scope --strict`.

## 7. Out-of-repo consumer

- [ ] 7.1 Update the `aleph-entity-graph` skill in `~/git/acordia-agents` so its prose names
      `collection` and `"*"`, and drops any `collection_ids` / `filters.collection_id` spelling.
      Raise it as its own change in that repository; this task tracks that it happened, since the
      spec names that consumer as a dependant.
- [ ] 7.2 Live suite: not run here. Every assertion above is observable without credentials, and
      the live suite needs a real instance and key.
