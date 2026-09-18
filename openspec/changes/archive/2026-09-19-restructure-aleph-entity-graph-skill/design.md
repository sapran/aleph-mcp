## Context

See `proposal.md` — Why. The design-relevant state:

- This repository ships one skill at `plugins/aleph/skills/aleph-entity-graph/SKILL.md`, 84 lines,
  advertised in `.claude-plugin/marketplace.json` and in `plugins/aleph/README.md`.
- A second, divergent document is published under the same slug by `acordia-analysts` (121 lines at
  6.19.1). Both are installed in the the measured profile, and reads of `skill://aleph-entity-graph` in
  that profile returned 84 lines 15 times and 101 lines 3 times inside the window; the cache also
  holds a 121-line `acordia-analysts` 6.19.1 copy, installed but not observed being read. Whether
  resolution is order-deterministic was not established; what is established is that one slug
  returned two different documents inside a single window, and neither document controls which.
- `openspec/specs/mcp-tool-surface/spec.md` already treats the skill as a named external consumer at
  four points (lines 13, 31, 55, 534), so the skill is inside this repo's spec surface already.
- The server's tool docstrings are the precise reference for arguments and semantics, but *how* a
  caller sees them is host-dependent: a direct-call host surfaces the schema with the tool, while
  a device-exposing host returns it only when asked. That asymmetry is why callers guessed `id`
  rather than reading `entity_id`, so the skill must tell the caller to obtain the schema, not
  assume it has already arrived. Anything the skill restates about the docstrings can also go stale
  independently — the current tool-inventory paragraph is an instance of that.

## Goals / Non-Goals

**Goals:**

- Make a `skill://` reference to this plugin's skill resolve to exactly one document.
- Put the facts that failed in the corpus where a delegated caller reads them.
- Make the skill propagate to subagents by being quotable, not by being re-typed.
- Keep the skill's byte size roughly flat: content is moved and demoted, not accumulated.

**Non-Goals:**

- No change to tool registration, validation, slimming, or any server behaviour is proposed.
  Validation errors are already explicit — a caption-shaped `entity_id` and an out-of-range `limit`
  are each refused with a message naming the constraint — and the outage failures are
  infrastructure, which guidance cannot prevent. What guidance changes is how a caller handles and
  reports an outage it cannot avoid.
- No attempt to make the two publishers' documents converge.
- No measurement of the restructured skill's effect. That needs fresh prospective arms, not this
  corpus, per the retrospective-split limitation recorded in `skill://omp-session-corpus-audit` §6.

## Decisions

**Rename this plugin's skill to `aleph-mcp-entity-graph` rather than asserting ownership of the
shared slug.** A rename is executable inside this repository and verifiable from the built plugin;
asserting ownership is not, because resolution belongs to the host. No plugin-qualified skill URI
syntax was observed on any host in scope — every reference in the corpus is an unqualified
`skill://<slug>` — so a slug rename is the only resolution available from inside this repository.
Were a qualified form to exist, it would be the non-breaking alternative and should be preferred.
Alternatives considered: (a) leave the collision and document it — rejected, since two publishers
claim the slug concurrently and any dispatch instruction inherits that ambiguity; (b) make the
`acordia-analysts`
removal a prerequisite — rejected, since it blocks a self-contained improvement on another
repository's release cycle, and the cross-repo change remains possible afterwards; (c) rename to a
name that drops "entity-graph" — rejected, it would lose the discoverability the description
depends on. Cost accepted: the slug is a published surface, so this is breaking for anyone
referencing it, and the change is marked as such.

**Restructure by moving content, with a reference file for what a deployment cannot reach.**
The order becomes: call contract, dispatch snippet, method, reporting discipline, guardrails, with
profile guidance alone moved to `references/profiles.md` behind the `profile_id` trigger. Entity-set
and cross-reference guidance stays in the method text: `list_entitysets` was called 8 times in the
window without error and no observed signal gates it, so it is reachable guidance and demoting it
would be unjustified by the profile evidence.
Alternative considered: a second top-level skill carrying the call contract — rejected on the
measurement, because the legs that read no Aleph skill would miss a second one exactly as they miss
the first; splitting halves the hit rate instead of raising it. The propagation problem is solved by
the dispatch snippet, which is why the snippet is a spec requirement rather than a nicety.

**Delete the skill's tool-inventory paragraph and defer to the server's docstrings.** The seventeen
names, their arguments and their semantics are authoritative in `src/aleph_mcp/server.py`, and the
skill directs the caller to read the mounted schema rather than carrying a second copy of it. The
skill keeps only what the docstrings cannot say: which argument spellings callers actually got
wrong, that a `caption` is not an identifier, and that the mount prefix and the invocation
mechanism belong to the host. Alternative considered: keep the
inventory and add a staleness test asserting it matches registration — rejected as a test that
guards prose duplication rather than removing it.

**Verify from the built plugin, not from the source tree.** Acceptance reads the skill as a consumer
would receive it — the file the plugin directory actually contains, at the renamed path, with no
residual copy at the old one. This follows `Before I claim it works`: stored is not effective, so the
check is on the artifact, and a grep for residual `skill://aleph-entity-graph` self-references is
part of it.

## Risks / Trade-offs

- **The rename breaks an existing reference.** → It is marked **BREAKING** in the proposal and in
  the capability description; `plugins/aleph/README.md` and the marketplace description move in the
  same change, and the plugin version is bumped so an installed copy is replaced rather than
  shadowed.
- **A leg still never reads the skill, because the lead omits the snippet.** → The snippet is a
  requirement with a scenario, so its absence is a spec failure; but nothing in this repository can
  compel an orchestrator to use it. This is the honest limit of the change and is stated rather than
  designed around.
- **Moving profile guidance out could read as deleting capability.** → It stays in the distributed
  skill as a reference file with a stated trigger, and the delta records the measurement (`profile_id`
  absent from 1,356 replies and 809 spilled payloads) and the reason it is demotion rather than
  deletion.
- **The restructure could grow the skill into something legs skim past.** → Size is held roughly
  flat by removing the tool inventory and demoting the profile prose, paying for the call contract
  and the reporting rules.
- **The corpus is one profile on one host over one week, with one dominant collection scope (511 of
  887 searches with a parsed body).** → Every requirement is justified by a failure mode that is mechanical rather
  than corpus-specific — argument spellings, identifier provenance, outage reporting — and the
  proposal states the window and scope so a later reader can re-measure rather than trust it.
