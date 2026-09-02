## Why

A live ACORDIA run on 2026-09-02 (opwe profile, collection 874 "Amster-Tele2") spent three
turns discovering how to scope a search to one collection. The transcript is
`~/.omp/profiles/opwe/agent/sessions/-ai-tasks-tele2-siem/2026-09-02T12-41-09-751Z_01a06223-3577-7383-a044-c14e6ea065f6.jsonl`:

1. `search_entities {"q": "kaspersky OR касперский", "collection": "874", ...}` → `total: 10000`
2. `search_entities {"q": "\"информационная безопасность\" ...", "collection": "874", ...}` →
   `total: 10000`, and the first row carries `collection_id: "833"`
3. `read xd://mcp__aleph_mcp_search_entities` — the model re-reads the tool schema mid-run
4. `search_entities {"q": "kaspersky OR касперский", "filters": {"collection_id": "874"}, ...}` →
   `total: 5695`

Step 2 is the real defect. The caller asked for one collection, was answered from another, and
nothing anywhere reported a problem. `10000` versus `5695` is not a paging artefact: the first
number is a different, unscoped result set that happened to succeed.

The wrong key never reached this server. Probed 2026-09-02: `search_entities` rejects an unknown
`collection` argument loudly (`ToolError: Unexpected keyword argument`), and no request is sent.
But the omp `xd://` MCP bridge **drops unknown keys before the call**, verified by sending
`{"bogus_unknown_key": "..."}` to a mounted MCP tool and receiving a clean result. So argument
validation cannot fix this, and neither can documentation the caller has already read: the model
sent a plausible key, the harness deleted it, and this server dutifully searched everything.

The cause it *can* fix is its own vocabulary. One server currently spells the same concept three
ways — `get_collection(collection=…)`, `xref_results(collection_id=…)`,
`match_entity(collection_ids=[…])` — and on the one tool where scope matters most,
`search_entities`, the concept has no parameter at all: it hides inside a free-form `filters`
dict. `collection` is the word the model reached for because this server taught it that word on
the neighbouring tool.

This is the same class as the two refusals already specified here. `limit + offset > 9999` is
refused rather than clamped, and the schema scope is disclosed in `searched`, both because a
confidently incomplete answer is a bug in this repository. An unscoped search returned in answer
to a scoped question is the same bug with a wider blast radius: it contaminates a product with
another casefile's data.

## What Changes

- **`search_entities` gains a required `collection` parameter.** An unscoped search becomes
  impossible to reach by accident. Searching every readable collection stays available but must
  be asked for by name, with the exact literal `"*"`.
- **One word for the concept across the whole tool surface.** `collection` replaces
  `collection_id` on `list_entitysets` and `xref_results`, and `collection_ids` on
  `match_entity`. Every one of them accepts a numeric id, a `foreign_id`, or a list, exactly as
  `get_collection` already does — so an id the caller holds in either form works on the first
  attempt, on every tool.
- **`filters={"collection_id": …}` is refused, not merged.** Two ways to say the same thing is
  how the ambiguity survives. The refusal names `collection` and states the value to pass.
- **The resolved scope is disclosed.** `searched` gains a `collection` key carrying the numeric
  ids actually searched, or `"*"`. A caller that reads only the rows can otherwise not tell
  which collections answered — which is exactly what step 2 above needed and did not have.
- **A `"*"` search is annotated.** The `_note` states that the result spans every readable
  collection, so a deliberate cross-collection search still reads as one in the transcript.
- Not a behaviour change, stated to bound the blast radius: the read-only allowlist in
  `readonly.py` is untouched, and every existing validation in `search_entities` — the 9999
  window, negative paging, the page-shrink loop — runs exactly as before. Collection resolution
  happens ahead of them and adds at most one cached `GET /api/2/collections` per foreign id.

## Impact

- **Breaking for callers**, deliberately. `search_entities` without `collection` now fails, where
  it previously searched everything. That is the point: the failure is loud, immediate, and names
  the fix, whereas the old success was silent and wrong. Three parameter renames break any caller
  passing them by keyword.
- **Out-of-repo consumer:** the `aleph-entity-graph` skill in the `acordia-analysts` plugin
  restates this server's limits and names its tools. Its prose must be updated in the same
  release, and is tracked as a task here rather than left to drift.
- **Modified code:** `src/aleph_mcp/client.py` (collection resolution, `search_entities`,
  `match_entity`, `list_entitysets`, `xref_results`), `src/aleph_mcp/server.py` (the four tool
  signatures, their docstrings, and the working-method `INSTRUCTIONS`).
- **Modified tests:** `tests/test_tools.py`, `tests/test_client.py`, `tests/shapes.py` — the
  search envelope must admit the new `searched.collection` key, and roughly twenty existing
  search tests must pass a scope.
