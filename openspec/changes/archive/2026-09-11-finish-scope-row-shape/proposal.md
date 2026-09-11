## Why

`guard-scope-resolver-shapes` guarded the collection listing's *envelope* — no `results` key, a
non-list `results`, a first row that is not a record — and left the row inside it, and the
reporting around it, where they were. Its own review parked four claims, all measured again on
`develop @ af104b7` before this proposal was written. None returns wrong rows; three produce a
confidently wrong diagnosis and one produces silence where a warning belongs.

- **A row that matches the foreign_id but carries an unusable `id` blames the caller.** The
  resolver hands `hit.get("id")` straight to `check_collection_id`, whose message is written for
  caller input. Measured end-to-end through the client for `id` null, missing, `"abc"` and
  `{"a": 1}` — all four give the same reply:

      invalid collection: expected a numeric collection id (got 'None'). A foreign_id is
      accepted directly and resolved for you; this error means the value is neither.

  The caller passed a valid foreign_id that the upstream confirmed one line earlier, and is told
  their value is "neither". That is the same confident wrong diagnosis `guard-scope-resolver-shapes`
  removed from the envelope, one branch further down — and a renamed or slimmed `id` field is a
  more likely upstream malfunction than `{"results": 5}`. Both reviewers of that change raised it
  independently; one rated it critical.

- **A row with no `foreign_id` key at all is read as a different collection.** The resolver tests
  `hit.get("foreign_id") != text`, so an absent field and a genuinely different value take the same
  branch. Measured: `{"results": [{"id": "874"}]}` produces *"no collection with foreign_id
  'my-case' is readable with this API key; call list_collections"*. Only a genuinely different
  value has any reading as a miss; a row with no `foreign_id` key is not a collection record at
  all, and the listing that carried it is not a listing this server can read.

- **A bare JSON array of records resolves and caches, with no listing envelope.** The transport
  wraps a non-dict body as `{"results": <body>}`, so a 200 whose body is
  `[{"foreign_id": "my-case", "id": "874"}]` resolves to 874, sends
  `filter:collection_id=874`, and caches `my-case -> 874` for the process lifetime. Measured.
  The resolver cannot tell an Aleph listing from any JSON array that happens to carry the right
  two keys — a proxy's cache dump, a fixture, another service's response to a redirected request.

- **`match_entity` never announces an all-collections scope.** `searched` is written only inside
  `search_entities`, so `match_entity(collection="*")` sends no constraint, returns every readable
  collection's rows, and says so nowhere. Measured: the reply carries exactly `limit`, `offset`,
  `results`, `total` — no `searched`, no EVERY COLLECTION note. That is the failure `scope.py`'s
  own module docstring says the module exists to prevent, reached through the one tool that is
  exempt from the reporting half of it.

## What Changes

- The row a listing resolves to SHALL be checked as a *collection record* before its `id` reaches
  the caller-facing validator. A row whose `id` is absent, is not a string or integer, or is not a
  numeric collection id is an upstream malfunction and SHALL be refused as one — not as an invalid
  argument, which is what it says today.
- A row carrying **no** `foreign_id` key SHALL be refused as an upstream malfunction, separately
  from a row whose `foreign_id` is present and names a different collection, which keeps the
  existing miss diagnosis naming `list_collections`.
- Rows SHALL NOT be trusted without a listing envelope. A body that carries a non-empty `results`
  but none of the envelope keys a listing has — `total`, `page`, `limit`, `offset`, `status` — is
  refused as an upstream malfunction. An **empty** `results` is deliberately exempt, so that a bare
  `[]` body keeps reading as the genuine miss the current spec fixes for it.
- **BREAKING** (one added response key and one added note, no signature change): `match_entity`
  SHALL report its resolved collection scope under `searched.collection`, exactly as
  `search_entities` does, and SHALL carry the EVERY COLLECTION note when that scope is `"*"`. The
  spec asserts the opposite today and is corrected by this change.
- Every new refusal path stays fail-closed: nothing resolves and nothing is cached.

## Capabilities

### New Capabilities

None. Three of the four sharpen the listing-shape contract `mcp-tool-surface` already states; the
fourth corrects a scenario in it that pins the absence of a warning.

### Modified Capabilities

- `mcp-tool-surface`: the *One vocabulary for collection scope across the tool surface*
  requirement gains the row-shape contract — the row's `id` and `foreign_id` are checked as
  upstream data before either is read as an answer, and a non-empty result set needs an envelope
  before its rows are trusted. The *A search must name its collection scope* requirement is
  corrected: `match_entity` reports `searched.collection` and the all-collections note rather than
  reporting neither.

## Impact

- `src/aleph_mcp/scope.py` — `CollectionResolver.resolve_one` (envelope check, `foreign_id`
  presence, row `id` guard) and `_unusable_listing` (a bounded value is now admissible in the
  shape phrase, for the one case where the type name says nothing).
- `src/aleph_mcp/client.py` — `match_entity` gains `searched.collection` and the EVERY COLLECTION
  note; `_reply`'s docstring claim that only `search_entities` sets `_note` becomes false and is
  corrected.
- `tests/test_scope.py`, `tests/test_collection_scope.py` — coverage for each new shape and for
  what `match_entity` now reports. One existing test changes subject: the bounded-echo test for an
  upstream `id` now pins the malfunction refusal rather than the caller-facing one.
- Two refusal messages change text, one response gains two keys. A caller that matched on the
  invalid-collection message for a *lookup* failure now sees the upstream-malfunction message; a
  caller that matched on it for its own bad argument is unaffected.
