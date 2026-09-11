## 1. Reproduce, red first

- [x] 1.1 Assert each untranslated shape raises the translated refusal instead: `{"results": {"a": 1}}`, `{"results": 5}`, `{"results": true}`. Each must fail today with `KeyError`/`TypeError`, which is the symptom the entry records.
- [x] 1.2 Assert each malfunction shape is refused *without* the `list_collections` next step: no `results` key, `{"results": null}`, `{"results": [null]}`, `{"results": "html page"}`.
- [x] 1.3 Assert `{"results": []}` still raises the authorisation-or-existence refusal naming `list_collections` — the one shape that keeps the old message.
- [x] 1.4 Assert nothing is cached after every refusal above (`resolver.cached` stays empty), and that a later successful lookup for the same foreign_id still resolves.
- [x] 1.5 Assert `parse_scope(["*"])` returns `None`, and that `["*", "*"]` does too.
- [x] 1.6 Assert `["*", "acme"]` and `["acme", "*"]` still raise the mixed-scope refusal, and `[]` still raises the names-nothing refusal.
- [x] 1.7 Assert the end-to-end tool behaviour for `["*"]`: `search_entities` applies no collection filter, sends no lookup, and reports `"*"` under `searched.collection`.
- [x] 1.8 Run the new tests and record that each fails with the symptom the entry names.

## 2. Guard the listing shape

- [x] 2.1 In `CollectionResolver.resolve_one`, branch on the listing shape before indexing: absent-or-null `results`, non-list `results`, empty list, non-record first row.
- [x] 2.2 Give the malfunction branches one refusal that names the shape received by type only, never by value, and that does not mention `list_collections` or the API key.
- [x] 2.3 Leave the empty-list branch on the existing message, and the verified-`foreign_id` check that follows unchanged.
- [x] 2.4 Keep every branch fail-closed: no `ResolvedCollection` returned, no cache write.
- [x] 2.5 Update the comment above the check to describe the branches, replacing the one that explains the single `isinstance` guard.

## 3. Accept the all-collections literal in either spelling

- [x] 3.1 In `parse_scope`, return `None` for a list whose every element is the literal, before the mixed-scope refusal.
- [x] 3.2 Keep the mixed-scope refusal for a list holding the literal alongside anything else, with its message unchanged.
- [x] 3.3 Note in the docstring that both spellings of the literal mean the same scope.

## 4. Verify

- [x] 4.1 Re-run the tests from group 1; all green.
- [x] 4.2 Mutation-test every new assertion: reintroduce each defect one at a time, confirm the matching test goes red with the recorded symptom, restore. A test that survives its own mutation certifies nothing.
- [x] 4.3 Update any existing test that asserted the old `["*"]` refusal or the old not-found text for a malfunction shape.
- [x] 4.4 Full suite, `ruff check`, `ruff format --check`, `mypy` — all clean.

## 5. Land

- [x] 5.1 `openspec validate guard-scope-resolver-shapes --strict`.
- [ ] 5.2 Sync the delta into `openspec/specs/mcp-tool-surface/spec.md` and archive the change.
- [ ] 5.3 Close entry 1 in `docs/implementation-notes.md`, renumber the work plan, and park anything found in passing.
- [ ] 5.4 Open the PR; run `code-reviewer`, `silent-failure-hunter` and `pr-test-analyzer` on the diff; fix or dismiss each finding; merge on green CI.

## Verification record

**Red first.** The 13 new assertions failed before the fix, each with the symptom the entry
records: `KeyError: 0` for `{"results": {"a": 1}}`, `TypeError: 'int'/'bool' object is not
subscriptable` for the number and boolean bodies, the `list_collections` diagnosis for every other
unusable shape, and the mixed-scope refusal for `["*"]` and `["*", "*"]`.

**Mutation-tested, 15 of 15 caught.** Each defect reintroduced alone, with bytecode writing
disabled so a same-size edit cannot be served from a stale `.pyc`:

| mutation | caught by |
|---|---|
| restore the original `or []` read | shape tests |
| drop the non-list guard | shape tests + e2e |
| drop the non-record first-row guard | shape tests + e2e |
| report an empty listing as a malfunction | the no-such-collection test |
| report a malfunction as a missing collection | the no-`list_collections` assertions |
| send a malfunction to `list_collections` anyway | the no-`list_collections` assertions |
| claim the API key is at fault | the no-`API key` assertion |
| echo the body value instead of its type, on either branch | the no-echo test |
| hard-code the type name, on either branch | the per-type test |
| cache the foreign_id before the shape is verified | the `cached == {}` assertions |
| drop the verified-`foreign_id` check | the unconfirmed-resolution test |
| refuse `["*"]` again | the either-spelling tests |
| `all` → `any` in `parse_scope` | the mixed-scope refusal tests |

The first pass found two survivors — nothing pinned the type name on the first-row branch, and
nothing pinned that the type name is read rather than hard-coded. Both closed by parametrising
across distinct types on both branches.

**Gate.** 540 passed, 31 skipped, 5 xfailed (518 before). `ruff check`, `ruff format --check` and
`mypy` clean on the package CI checks.
