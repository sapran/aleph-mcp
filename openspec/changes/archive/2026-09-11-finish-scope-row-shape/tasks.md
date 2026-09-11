## 1. Reproduce, red first

- [x] 1.1 Assert a confirmed row with an unusable `id` — absent, null, `"abc"`, a mapping, a list — is refused as an upstream malfunction, not as an invalid argument. Each must fail today with *"expected a numeric collection id … the value is neither"*.
- [x] 1.2 Assert that refusal quotes the id, clipped to the shared echo bound and with control characters escaped — the coverage the two existing echo tests carry, moved to the new message.
- [x] 1.3 Assert a first row with no `foreign_id` key is refused as an upstream malfunction and does not name `list_collections`. Must fail today with the missing-collection diagnosis.
- [x] 1.4 Assert a first row whose `foreign_id` is present but different — including null — still raises the missing-collection refusal naming `list_collections`.
- [x] 1.5 Assert a bare JSON array of records is refused rather than resolved: no search sent, nothing cached. Must fail today by resolving `874` and caching it.
- [x] 1.6 Assert a body carrying any one of `status`, `total`, `page`, `limit`, `offset` beside its rows still resolves, and that a bare empty array still reads as a miss.
- [x] 1.7 Assert `match_entity` reports `searched.collection` for a named scope and for `"*"`, in both spellings of the literal, and carries the EVERY COLLECTION note only for the literal. Must fail today — the reply carries neither key.
- [x] 1.8 Assert nothing is cached after each new refusal, and that a later well-formed lookup for the same foreign_id still resolves.
- [x] 1.9 Run the new tests and record that each fails with the symptom the entry names.

## 2. Check the row as a collection record

- [x] 2.1 Extract the collection-id predicate so `check_collection_id` and the row guard cannot drift apart.
- [x] 2.2 Guard the row's `id` before the caller-facing validator; route a failure to `_unusable_listing` with the value quoted under `COLLECTION_ECHO` and `!r`.
- [x] 2.3 Amend `_unusable_listing`'s docstring: a bounded value is admissible where a type name is not the diagnosis, and why this is the only such branch.
- [x] 2.4 Split the `foreign_id` test into key-absent (malfunction) and value-differs (miss), on key presence rather than falsiness.
- [x] 2.5 Correct the comment in `check_collection_id` that calls the upstream `id` its one non-caller path — after 2.2 it has none.

## 3. Require a listing envelope before trusting rows

- [x] 3.1 Add the envelope check after the first-row-is-a-record branch and before the row is read, skipped for an empty `results`.
- [x] 3.2 Name the accepted envelope keys once, beside the other wire vocabulary this module owns.
- [x] 3.3 Extend the branch comment above the checks to cover the three new branches and say why the empty list is exempt.

## 4. Report the scope `match_entity` searched

- [x] 4.1 Hoist the EVERY COLLECTION note to a module constant in `client.py`; `search_entities` reads it from there.
- [x] 4.2 Write `searched.collection` in `match_entity`, and the note when the scope is the literal.
- [x] 4.3 Correct `_reply`'s docstring, which says only `search_entities` sets `_note`.
- [x] 4.4 Rewrite `test_match_entity_reads_the_literal_the_same_way_in_either_spelling`, whose docstring and assertion pin the absence this change removes.

## 5. Verify

- [x] 5.1 Re-run the tests from group 1; all green.
- [x] 5.2 Mutation-test every new assertion: reintroduce each defect one at a time with bytecode writing disabled, confirm the matching test goes red with the recorded symptom, restore.
- [x] 5.3 Check the tool path, not just the client: each new refusal arrives through `mcp.call_tool` as an unprefixed `ToolError`, and `match_entity`'s new keys survive the MCP seam.
- [x] 5.4 Full suite, `ruff check`, `ruff format --check`, `mypy` — all clean.

## 6. Land

- [x] 6.1 `openspec validate finish-scope-row-shape --strict`.
- [ ] 6.2 Sync the delta into `openspec/specs/mcp-tool-surface/spec.md` and archive the change.
- [ ] 6.3 Close entry 1 in `docs/implementation-notes.md`, renumber the work plan, and park anything found in passing.
- [ ] 6.4 Open the PR; run `code-reviewer`, `silent-failure-hunter` and `pr-test-analyzer` on the diff; fix or dismiss each finding; merge on green CI.

## Verification record

**Measured first, on `develop @ af104b7`.** All four claims reproduced end-to-end through
`AlephClient` before a line was written: `id` null/missing/`"abc"`/`{"a": 1}` each answered
*"expected a numeric collection id (got 'None'). … this error means the value is neither"*; a row
of `{"id": "874"}` answered *"no collection with foreign_id 'my-case' is readable with this API
key; call list_collections"*; a bare `[{"foreign_id": "my-case", "id": "874"}]` resolved, sent
`filter:collection_id=874` and cached `my-case -> 874`; `match_entity(collection="*")` returned a
reply whose only keys were `limit`, `offset`, `results`, `total`.

**Red first.** 16 new assertions failed before the fix, each with the symptom above.

**Mutation-tested, 22 of 22 caught**, reproduced twice. Each defect reintroduced alone with
bytecode writing disabled (`python -B`), so a same-size edit cannot be served from a stale `.pyc`:

| mutation | caught by |
|---|---|
| restore the caller-facing validator for the row's `id` | the row-malfunction rows |
| drop the row-`id` guard entirely | the row-malfunction rows |
| echo the raw `id`, unbounded | the bounded-echo test |
| drop the `!r`, leaving control characters raw | the bounded-echo test |
| route a bad `id` to the missing-collection refusal | the no-`list_collections` assertions |
| name the clause but drop the value | the exact-clip assertion |
| `match` instead of `fullmatch` in the shared predicate | the trailing-newline and spaced rows |
| the shared predicate always true | the row-malfunction rows |
| drop the `foreign_id` key-presence branch | the no-`foreign_id`-key row |
| discriminate on falsiness rather than key presence | the null and empty `foreign_id` misses |
| route the absent key to the missing-collection refusal | the no-`list_collections` assertions |
| drop the envelope branch | the bare-array tests, unit and e2e |
| test envelope truthiness rather than key presence | the `offset: 0` row |
| require every envelope key rather than any one | the per-key rows |
| drop `offset` from the accepted keys | the `offset` row |
| check the envelope before the empty-`results` branch | the empty-exemption test |
| check the envelope before the first-row branch | the branch-order test |
| drop `match_entity`'s `searched` key | both match tests |
| report the scope bare rather than under `collection` | both match tests |
| drop `match_entity`'s every-collection note | the literal test |
| emit that note unconditionally | the named-scope test |
| drop the hoisted constant from `search_entities` | the existing `"*"` tests |

**Tool-path check.** The claims are about what a *model* sees, so they were read off the MCP seam
rather than off the client. All three new refusals arrive through `mcp.call_tool("search_entities",
…)` as unprefixed, printable `ToolError`s — 450, 427 and 432 characters. `match_entity` through the
same seam reports `searched={'collection': '*'}` with the EVERY COLLECTION note for the literal,
and `searched={'collection': ['874']}` with no note for a named scope.

**Four unrealistic fixtures corrected.** Four `tests/test_client.py` listings were hand-built as
`{"results": [...]}` with no envelope, so the new guard refused them. Checked against the real
contract before changing them rather than assumed: `list_collections` reads `total`, `limit` and
`offset` off that same `/api/2/collections` endpoint, and `tests/live/test_live.py` asserts
`out["total"] is not None` against a live instance. The fixtures were the thing that was wrong.

**One existing assertion re-aimed.** `test_an_upstream_id_echoed_into_an_error_is_bounded` capped
the whole message at 500 characters. The value now arrives through the upstream-malfunction
refusal, whose fixed prose is longer: 581 characters total, of which 444 are this server's own
constants and 137 are the clipped echo of a 5000-character id. A whole-message ceiling was
therefore pinning the length of a sentence rather than the bound, and this file has already had one
assertion silently disarmed by a rewording. The test now bounds the echo directly — no run of 121
upstream characters may appear — keeps the exact-clip assertion, and leaves the whole-message
figure as a coarse backstop set well clear of the prose.

**Gate.** 644 passed, 31 skipped, 5 xfailed (620 before). `ruff check`, `ruff format --check` and
`mypy` clean.
