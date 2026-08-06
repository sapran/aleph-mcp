## Why

Aleph's answer to the identity question was unreachable through this server. When an
investigator decides that several entities are the same real-world actor, Aleph records that
decision as a *profile* — an EntitySet with a party, holding the constituent entities and a
merged pseudo-entity combining their properties. The twelve shipped tools exposed only the
*inputs* to that decision (`similar_entities`, `xref_results`, `match_entity`: scored candidate
lists) and never the decision itself, so a consumer was told to resolve identity while being
given only hypotheses to do it from.

The gap was invisible because discovery already worked: Aleph indexes `profile_id` on entities
and `slim_entity` already passes it through, so every search hit was quietly announcing a
resolved identity that no tool could read.

Two smaller defects are fixed alongside, both of them the server asserting something false
about Aleph:

- `INSTRUCTIONS` claimed entity search `q` carries "a fuzzy boost Aleph adds on top". It does
  not. The fuzzy `multi_match` overlay is added by `CollectionsQuery` only, so it applies to
  `/api/2/collections?q=` and never to `/api/2/entities?q=`. A consumer trusting that claim
  manufactures false negatives on exactly the misspelt and transliterated names that matter.
- `GET /api/2/entitysets/<id>` was unwrapped, so a consumer could read a curated set's contents
  but never the set's own record — the curator's type, label and summary, which is where the
  intent behind the set lives.

## What Changes

- Five new read tools: `get_profile`, `profile_tags`, `profile_similar`, `expand_profile`,
  `get_entityset`. Tool count goes 12 to 17; every one is a GET.
- Five new allowlist entries in `readonly.py`, all GET. The method pin becomes load-bearing for
  the first time: the accepted id charset includes `_`, so the GET rule for
  `/api/2/profiles/<id>` also matches the path of `POST /api/2/profiles/_pairwise`, an Aleph
  write that records a judgement and can create or merge a profile. Only the absence of a POST
  rule refuses it, so that is now asserted by a named test rather than left to the general
  negative case.
- `get_profile` passes `merged` through `slim_entity`. A merged proxy inherits its
  constituents' properties, so a merged-in Document drags `bodyText` with it; without slimming
  this tool would be the one hole in the no-document-text guarantee.
- `list_entitysets`' inline projection is extracted to `_slim_entityset`, which
  `get_entityset` reuses with `full=True`. Same list-vs-detail shape as `_slim_collection`, and
  the two projections can no longer drift.
- `get_entityset` reports a `_note` when Aleph 302-redirects it to the profile view. That
  redirect is also why the profile path must be allowlisted for this tool to work at all: the
  read-only hook runs on every redirect hop.
- `INSTRUCTIONS` and `README.md` state what `q` actually does: not fuzzy, 66%
  `minimum_should_match` on multi-term queries, `match_entity` as the name-lookup path.

Not wrapped, deliberately: `/api/2/collections/<id>/reconcile` and `/api/freebase/*` build
`MatchQuery` from the same engine as `POST /api/2/match`, under the same permission, and return
a worse shape (`r:score`, `type` as an array, `match` hardcoded false). They duplicate
`match_entity` and buy no capability. See `design.md`.

## Capabilities

### New Capabilities

None. Both affected capabilities already exist.

### Modified Capabilities

- `mcp-tool-surface`: the registered tool names are a published contract and the enumeration
  grows from twelve to seventeen. The no-document-sized-text requirement now also binds
  `get_profile`'s `merged` field.
- `read-only-guard`: the allowlist gains five GET pairs, and the requirement must record that
  the method half of a pair is what refuses a write whose path matches an allowlisted GET
  regex.

## Impact

- `src/aleph_mcp/readonly.py` — five allowlist entries; comment recording the `_pairwise`
  hazard and why `_ENTITY_ID` must not be narrowed to hex to "fix" it.
- `src/aleph_mcp/client.py` — new `# -- profiles --` section with four methods; `get_entityset`
  and `_slim_entityset`; `list_entitysets` refactored onto the shared projection.
- `src/aleph_mcp/server.py` — five tool registrations; corrected `INSTRUCTIONS` (step 4 names
  the profile cluster, hard-limits bullet no longer claims fuzziness).
- `tests/test_readonly.py`, `tests/test_client.py`, `tests/test_tools.py`,
  `tests/live/test_live.py` — `EXPECTED_TOOLS` grows to 17; new positive allowlist rows;
  `test_pairwise_judgement_is_blocked`; slimming, redirect and validation coverage per tool.
- `README.md` — Surface table rows; "twelve tools" to "seventeen"; the same `q` correction.
- No dependency, transport or configuration change. No write capability is added.
- Downstream: acordia's `aleph-entity-graph` skill cites this tool surface and is updated
  separately in that repo; this server still registers names unprefixed and still does not
  guarantee any mount prefix.
