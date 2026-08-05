## Why

This server has a consumer that lives in another repository and pins an older version of the contract. The `aleph-entity-graph` skill, shipped in the `acordia-analysts` plugin at `2.0.0`, names our tools (`aleph_search_entities`, `aleph_expand_entity`, `aleph_get_entity_text`) and tells its analysts that they "enforce Aleph's real limits and strip document text out of search hits".

`baseline-mcp-tool-surface` made both of those claims contractual on our side. What is still missing is any machine-visible link between the two repositories: `openspec doctor` here reports `References: (none declared)` and `openspec store list` is empty, so the coupling exists only as prose — in `docs/implementation-notes.md` on this side, and in an archived proposal inside a plugin cache on the other.

The two repositories deliberately do not merge. acordia is markdown-only by contract, stated in its `CLAUDE.md` and `README.md` and normatively in `openspec/specs/operator-skill-library/spec.md`; its archived change `2026-07-31-aleph-data-access`, the one that created the skill, already ruled that `aleph-mcp` "is not and must not be vendored here". This change does not revisit that. It declares the edge that should have existed alongside it.

## What Changes

- Register the acordia repository as an OpenSpec store, and record its id and local path so the registration is reproducible rather than a one-off on one machine.
- Declare the dependency from this root so `openspec doctor` reports it instead of `(none declared)`.
- Verify what the declaration actually buys before relying on it — whether `doctor` reports drift across roots, or merely records the relationship. Scope the rest of this change to what it really does; if the answer is "records only", say so plainly rather than implying a check that does not run.
- Fold the prose in `docs/implementation-notes.md` down to a pointer once the declaration carries the same information, so the seam is described in one place.

**Open question for design, not to be guessed at here:** whether the tool-name expectation should be asserted mechanically from this side — for example a test that fails when a registered tool name is absent from the consumer's documented list — or whether that inverts the dependency in a way this repository should not accept. Declaring the reference is the prerequisite for having that conversation with evidence; it is not itself the answer.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is repository and tooling configuration; no behavioural requirement changes. Set `skip_specs: true` in `.openspec.yaml` unless the design concludes the reference belongs in a spec after all.

## Impact

- **Modified files:** `openspec/config.yaml` or the equivalent reference declaration; `docs/implementation-notes.md`.
- **Modified code:** none.
- **Nothing in acordia is touched.** The declaration is one-directional, from this root outward.
- **Risk:** a store registration is machine-local. If it does not survive a fresh clone, the declaration is documentation with extra steps — which is worth knowing, and is exactly what the verification step above is for.
- **Sequencing:** deliberately last of the three follow-ups. It points at `mcp-tool-surface`, which must exist in `openspec/specs/` first.
