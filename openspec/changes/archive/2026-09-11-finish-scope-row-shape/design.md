## Context

`src/aleph_mcp/scope.py` and `src/aleph_mcp/client.py`, on `develop @ af104b7`.

`CollectionResolver.resolve_one` now guards the listing's envelope in four branches and then does
this:

```python
if hit.get("foreign_id") != text:
    raise _no_such_collection(text)
resolved = check_collection_id(hit.get("id"))
self._cache[text] = resolved
```

Everything before those three lines asks *is this a listing*. Nothing asks *is this row a
collection record*, and nothing asks whether the body that carried it was a listing envelope at
all. Measured against the live tree, through `AlephClient`:

| lookup body | today |
|---|---|
| `{"total": 1, "page": 1, "results": [{"foreign_id": "my-case"}]}` | *expected a numeric collection id (got 'None') … the value is neither* |
| `…"results": [{"foreign_id": "my-case", "id": "abc"}]` | *…(got 'abc') … the value is neither* |
| `…"results": [{"foreign_id": "my-case", "id": {"a": 1}}]` | *…(got "{'a': 1}") … the value is neither* |
| `{"total": 1, "page": 1, "results": [{"id": "874"}]}` | *no collection with foreign_id 'my-case' is readable with this API key; call list_collections* |
| `[{"foreign_id": "my-case", "id": "874"}]` | resolves 874, sends `filter:collection_id=874`, caches `my-case -> 874` |

and through `client.match_entity(sample={"schema": "Person"}, collection="*")`:

    reply keys = ['limit', 'offset', 'results', 'total']

The first three rows are the same defect `guard-scope-resolver-shapes` fixed for the envelope,
arriving one branch lower: an upstream malfunction given a diagnosis written for the caller. The
fourth is the confident wrong diagnosis in its other direction — a row that is not a collection
record reported as a collection that does not exist. The fifth is a missing question rather than a
wrong answer. The sixth is silence where the module's own reason for existing says a warning
belongs.

## Goals / Non-Goals

**Goals.** Every conclusion the resolver draws about a row is earned from something the row
actually says. Every refusal about an upstream shape reads as being about the upstream. A
cross-collection `match_entity` announces itself the way a cross-collection `search_entities` does.

**Non-Goals.** No change to what resolves successfully on a well-behaved Aleph instance — every
branch added here refuses, none accepts something previously refused. No change to the miss
diagnosis for the shapes that genuinely mean "no such collection". No new dependency, no tool
signature change, no widening of `readonly.py`.

## Decisions

### 1. The row's `id` is validated as upstream data, and the refusal carries the value

`check_collection_id` exists for caller input: its message offers the caller the foreign_id
alternative, which is a step the caller can take. Handing it upstream text produces a sentence
that is false about the call — the caller's value *was* a foreign_id, and it *did* resolve.

The row's `id` is therefore tested before that validator, with the same predicate, and a failure
goes to `_unusable_listing`. The predicate is extracted (`_reads_as_collection_id`) rather than
duplicated, so the two paths cannot drift into disagreeing about what a collection id is — the
same reason `_COLLECTION_ID` is shared with `readonly.py` by construction.

**The refusal names the value, not the type**, which is the one deliberate exception to
`_unusable_listing`'s rule. For every other branch a type name is the whole diagnosis: `results as
dict` says "an object where a list belongs". For an `id` it says nothing — `"abc"` and `"874"` are
both `str`, and the difference between them is the entire finding. The value is admissible here
because the bound it needs already exists at this exact call site and is already tested twice:
`render(text, COLLECTION_ECHO)` clips it and `!r` escapes the control characters that policy
deliberately does not strip. Both existing echo tests keep their subject and move to the new
message, so the bound does not lose its coverage in the move.

### 2. An absent `foreign_id` key is a malfunction; a different `foreign_id` value is a miss

`hit.get("foreign_id") != text` collapses two different upstream statements. A row saying
`foreign_id: "someone-else"` is a real collection record that is not the one asked for — a
leniency somewhere upstream, and the existing miss refusal is the one the spec already fixes for
it. A row with no `foreign_id` field has not made a statement about any collection; it is not a
collection record, and the body that carried it is not a listing this server can read.

The discriminator is key presence (`"foreign_id" not in hit`), **not** falsiness. A collection
genuinely created without a foreign_id serialises as `foreign_id: null`, which is a record
truthfully saying it is not the collection asked for: a miss, unchanged.

### 3. Rows are trusted only inside a listing envelope — and only when there are rows

`Transport.request` wraps a non-dict JSON body as `{"results": <body>}`, which is what lets a bare
array of records resolve. The wrapper produces that key **and nothing else**, while Aleph's
`QueryResult` serialiser always emits `status`, `total`, `page`, `limit` and `offset` beside the
rows. Requiring at least one of those five before reading a row separates the two by what they
actually contain, rather than by guessing at the body's provenance.

**The check is skipped for an empty `results`.** That is load-bearing, not an economy. The current
spec states that a bare `[]` body reads as a genuine miss — an empty array is an empty result set
whoever serialised it — and requiring an envelope unconditionally would silently reverse that
sentence while claiming to be about rows. The guard is about *trusting rows*, so it runs where
there are rows to trust.

**The check runs after the first-row-is-a-record branch,** so a body like `["x"]` keeps the more
specific diagnosis it has today (*carried a first row as str, not a record*) rather than the
weaker envelope one. Naming the row shape is more actionable for an operator than naming the
absent envelope, and both statements are true of that body.

Resulting branch order in `resolve_one`, each with one message:

1. `results` absent or null → *carried no results at all*
2. `results` not a list → *carried results as `T`, not a list*
3. `results` empty → **miss** (`list_collections`)
4. first row not a record → *carried a first row as `T`, not a record*
5. **new** — no envelope key → *carried rows with no listing envelope*
6. **new** — row has no `foreign_id` key → *carried a first row with no foreign_id field*
7. row's `foreign_id` ≠ asked → **miss** (`list_collections`)
8. **new** — row's `id` not a collection id → *carried a first row whose id is `…`, not a numeric collection id*
9. cache and return

### 4. `match_entity` reports the scope it searched

`search_entities` writes `searched.collection` and the EVERY COLLECTION note; `match_entity`
resolves the identical scope through the identical resolver and writes neither. The asymmetry is
not a decision anyone made — `searched` grew inside `search_entities` for the schema scope and the
collection was added beside it, so the tool without a schema scope got nothing.

`match_entity` therefore gains `searched.collection` and the same note. `searched` there carries
`collection` only: the schema is stated by the caller inside `sample`, so there is no schema scope
for this server to report back. The spec's own wording already anticipates this — the scenarios
assert their own key within `searched` rather than the whole of it.

The note text becomes a module constant rather than being copied. Two call sites for one sentence
is how the wire spellings of the collection filter ended up written three times, which is the
defect `scope.py` exists to have fixed.

### 5. What this change deliberately does not do

`_no_such_collection` is still raised from two places, and its docstring still says so. Splitting
the miss diagnosis further — a row naming a different collection is more likely an upstream
leniency than a missing collection — is a separate question about a shape that is already
correctly refused, and it is not among the four claims this change closes.

## Risks / Trade-offs

**An instance whose collection listing omits every envelope key stops resolving foreign_ids.** No
Aleph version does — `QueryResult` has emitted `status`/`total`/`page`/`limit`/`offset` throughout
the API's v2 life — and five accepted keys is a wide net. The failure is loud, fail-closed and
names the shape, which is the behaviour this whole entry is about. A proxy that rewrites the body
down to bare rows is exactly the case the guard is for.

**A caller matching on the invalid-collection refusal text for a lookup failure sees new text.**
That refusal was wrong about the call, which is why it is changing; a caller matching on it for
its own malformed argument is unaffected, because that path is untouched.

**`match_entity` replies grow by two keys.** `searched.collection` is a short list of numeric ids
or the literal; the note is a fixed sentence and appears only for `"*"`. Both are bounded and
neither carries upstream text.
