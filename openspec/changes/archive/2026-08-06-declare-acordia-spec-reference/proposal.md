## Why

This server has a consumer that lives in another repository and depends on its
contract. The `aleph-entity-graph` skill, shipped in the `acordia-analysts`
plugin (now at `2.1.0`), selects our tools by their bare verbs — the seventeen
names pinned by `mcp-tool-surface`, including the profile cluster — and tells
its analysts that these tools enforce Aleph's real limits and strip
document-sized text out of search hits. The skill matches on the verb and
states that any `aleph_` prefix is applied by the host mount, not guaranteed by
this server; that reading agrees with our `mcp-tool-surface` requirement that
tool names are registered unprefixed.

`baseline-mcp-tool-surface` and `extend-profile-tool-surface` made those claims
contractual on our side. What was still missing is any machine-visible link
between the two repositories: `openspec doctor` here reported
`References: (none declared)` and `openspec store list` was empty, so the
coupling existed only as prose — in `docs/implementation-notes.md` on this side,
and in an archived proposal inside a plugin cache on the other. This change
declares that edge.

The two repositories deliberately do not merge. acordia is markdown-only by
contract, stated in its `CLAUDE.md` and `README.md` and normatively in
`openspec/specs/operator-skill-library/spec.md`; its archived change
`2026-07-31-aleph-data-access`, the one that created the skill, already ruled
that `aleph-mcp` "is not and must not be vendored here". This change does not
revisit that. It declares the edge that should have existed alongside it.

## What Changes

- Declare the dependency in `openspec/config.yaml` under `references:`, naming
  the store id `acordia` and its git remote so the edge is reproducible rather
  than a one-off on one machine. `openspec doctor` now reports the reference
  instead of `(none declared)`, and prints a clone-and-register recipe.
- **Decision: declare, do not register.** The store is intentionally NOT
  registered on this machine. Verifying the mechanism (see below) showed that
  `openspec store register` writes a `.openspec-store/store.yaml` identity file
  into the store root — i.e. into acordia. That contradicts the one-directional
  seam this change exists to respect, so the earlier plan to "register acordia
  as a store" was dropped in favour of a config-only declaration. Nothing is
  written to acordia; the reference resolves to acordia only for a contributor
  who runs the printed register recipe against their own checkout.
- Fold the deferred prose in `docs/implementation-notes.md` down to a pointer,
  now that the declaration carries the seam.

**Open question, now answered with evidence.** The proposal asked whether the
tool-name expectation should be asserted *mechanically* from this side. It
should not, and this declaration does not do it: OpenSpec references are
records-and-index only. `dist/core/references.js` states it plainly — "Content
is never inlined; root resolution is never affected; problems degrade to
`warning` diagnostics". A declared reference, once its store is registered
locally, indexes the referenced root's spec ids and Purpose lines as read-only
upstream context; it runs no cross-root drift check and cannot fail this repo's
validation when a consumer name drifts. So the declaration buys visibility and a
reproducible fetch recipe — not enforcement. Asserting that our seventeen tool
names appear in acordia's skill would invert the dependency and is deliberately
left undone.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is repository and tooling configuration; no behavioural requirement
changes. `.openspec.yaml` sets `skip_specs: true`.

## Impact

- **Modified files:** `openspec/config.yaml` (new `references:` block);
  `docs/implementation-notes.md` (deferred section folded to a pointer).
- **Modified code:** none.
- **Nothing in acordia is touched.** The declaration is one-directional, from
  this root outward, and — per the decision above — the store is not registered,
  so no file is written into acordia.
- **Risk:** the reference resolves to acordia's specs only on a machine where a
  contributor has cloned and registered acordia with `--id acordia`. Unregistered,
  `doctor` reports the edge as a warning carrying the register recipe. That is
  the intended records-only state, not a failure.
- **Sequencing:** done last of the three follow-ups, after
  `extend-profile-tool-surface` archived the seventeen-tool surface it points at
  and after acordia's `extend-aleph-analyst-capability` moved the skill to the
  bare-verb form this proposal describes.
