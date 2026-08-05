# Implementation notes

Findings recorded during other work, kept out of the change that surfaced them. An entry leaves
this file when it becomes a spec requirement or is fixed — not when someone remembers to tidy up.

Retired since the last prune:

- The `$` anchor letting `entity_id="e1\n"` through, and `entityset_id=".."` normalising away to
  a different endpoint. **Fixed** by `fix-id-validation-anchors`; the validators now use
  `re.fullmatch`, as the allowlist always has.
- The guard matching a decoded path while the transport sends the encoded one. **Specified** by
  `baseline-read-only-guard` as a requirement that carries its own invalidating condition, with
  `test_id_charset_excludes_percent` as the tripwire: if `%` is ever added to the accepted id
  charset, that test fails and the guard must move to `raw_path`.
- `GET /api/2/collections/{id}?refresh=true` asking Aleph to recompute statistics. **Specified**
  by `baseline-read-only-guard` as the single named exception to "asks the server only to
  answer", with `test_refresh_is_emitted_by_exactly_one_request` as the tripwire so the exception
  list cannot grow quietly.

## Deferred: declare the acordia ↔ aleph-mcp seam as an OpenSpec reference

Not implemented. Recorded here so the decision is not re-derived from scratch.

This server has an external consumer that is not in this repository: the `aleph-entity-graph`
skill in the `acordia-analysts` plugin (`acordia` marketplace, pinned at 2.0.0). Its SKILL.md
names our tools (`aleph_search_entities`, `aleph_expand_entity`, `aleph_get_entity_text`), and
asserts on our behalf that the server "enforce[s] Aleph's real limits and strip[s] document text
out of search hits". Nothing checks either claim.

The two repositories deliberately do not merge. acordia is markdown-only by contract — stated in
its `CLAUDE.md`, its `README.md`, and normatively in
`openspec/specs/operator-skill-library/spec.md` ("the repository remains markdown-only") — and
its archived change `2026-07-31-aleph-data-access`, the one that created the skill, already ruled
that `aleph-mcp` "is not and must not be vendored here". Folding this package in would falsify a
deployed requirement there, and would drag a live-Aleph integration suite into a repo whose
stated test count is zero. The boundary stays.

What is missing is not a merge but a declared edge. `openspec doctor` in this repo reports
`References: (none declared)`, and `openspec store list` is empty, so the coupling exists only as
prose in an archived proposal in someone else's plugin cache. Registering acordia as an OpenSpec
store and declaring the dependency would make the seam machine-checkable from this side without
touching acordia at all.

Deferred rather than done because it changes how this repo resolves its OpenSpec root, which is
worth settling on its own rather than as a rider on the first baseline. Do it after
`baseline-mcp-tool-surface` lands, so there is something on this side for the reference to point
at.
