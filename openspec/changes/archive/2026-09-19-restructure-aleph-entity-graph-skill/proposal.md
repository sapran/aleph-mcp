## Why

A week of real analyst traffic shows the skill this plugin ships is not reaching the agents that do
the work. Every figure below is reproduced by `evidence/audit_aleph_usage.py`, whose scope, join keys
and denominators are stated in `evidence/README.md`: one agent profile's session corpus, event
timestamps in the closed, immutable window
`[2026-09-11T00:00:00Z, 2026-09-18T00:00:00Z)` — seven complete UTC days.

**1,356 executed Aleph tool calls across 41 sessions, 127 of them failing (9.4%)**. Of the 1,349 calls made
in the 37 sessions that issued five or more, **740 (55%) came from subagent legs that never read
any Aleph skill** — the heaviest such leg made 109 calls. Leads read the skill and then retype its
rules into each dispatch by hand: **168 rule-bearing lines, 52,843 characters (~13.2k tokens) across
30 dispatches**.

The skill is also not being used as an entity-graph skill. Search and document text are **1,057
calls (77.9%)**, while every graph pivot together — `expand_entity`, `entity_tags`, `match_entity`,
`similar_entities`, `xref_results` — is **23 calls (1.7%)**.

And `skill://aleph-entity-graph` does not identify a document. Two installed plugins publish that
slug concurrently: this plugin's 84-line copy and `acordia-analysts` 6.19.1 at 121 lines. Reads in
that profile returned 84 lines 15 times and 101 lines 3 times — two publishers answering one slug
inside the window. The plugin cache currently also holds the 121-line `acordia-analysts` 6.19.1
copy; that is a present installed document, not an observed read. Whether the host resolves deterministically was not established;
two publishers claiming one slug is enough.

## What Changes

- **Restructure the shipped skill around what a leg reads first.** Move the mechanical call contract
  into the opening section, because the top of an 84-line document is what an instructed leg
  actually consumes. It must carry the argument spellings that failed — `entity_id`, never `id` or
  `entity` (12 calls) — the rule that an identifier comes from a result's `id` field and never from
  a caption (10 calls passed captions such as `Email 10000000.0a1b…`), that `schema`/`schemata` are
  top-level arguments and not `filters` keys, that `collection` is required on `search_entities` and
  `match_entity`, and that the invocation mechanism belongs to the host and is read from the mounted
  tool schema rather than assumed — a device-exposing host takes a JSON object written to a device and
  returns its schema on request, a direct-call host does not. Of **29 identifier-handling failures
  across 8 sessions, 22 are directly preventable by these facts**; the remaining 7 are `404`s
  whose cause the corpus does not establish.
- **Add a dispatch snippet the lead pastes verbatim** into every leg assignment, naming the skill to
  read before the first Aleph call. This is the propagation fix and it retires the 168 hand-written
  rule lines.
- **Add outage-and-absence discipline.** 54 infrastructure failures across 9 sessions, worst at
  one leg (21 of 32 calls) and another (9 of 20). Both legs diagnosed the 503
  correctly and backed off, yet the first still closed with "The register is coherent and
  final. The deliverable is complete." A coverage statement must carry failed calls, and an empty
  result is not absence until the scope searched is stated — 65 of the 887 searches that
  succeeded and retained a result returned zero rows.
- **Sharpen the precision rule that is not landing.** Across the 887 searches whose JSON body
  parsed, `filters` appear in 7 (0.8%) against a skill that says precision comes from filters
  "always", while 78 (8.8%) are unquoted multi-term `q` walking into the 66%-of-terms widening.
  Facet-first, by contrast, is genuinely internalised — 649 of those searches carry `facets` and 29
  of 35 searching sessions faceted at least once — which is the evidence that a concrete rule does
  teach a habit here.
- **Demote the profile guidance alone to a reference file.** `profile_id` appears **zero times,
  populated or null, in all 1,356 replies and in all 809 spilled result logs**, every one of which
  carries ordinary entity fields (`schema`, `caption`) — so the zero is a real absence, not an
  artefact of reading the wrong copy. The server forwards `profile_id` whenever Aleph supplies it
  (`src/aleph_mcp/client.py:298`), so this is the instance never offering a profile rather than
  analysts ignoring advice: unreachable here, still correct for an instance with curated profiles.
  Entity-set and cross-reference guidance stays in the method text, because it was reachable and
  used — `list_entitysets` was called 8 times without error and nothing gates it.
- **Resolve the skill-name collision by renaming this plugin's copy** to `aleph-mcp-entity-graph`,
  which is executable inside this repository alone: the slug becomes unambiguous, every `skill://`
  reference in this repo's docs, dispatch snippet and plugin manifest moves with it, and
  `aleph-entity-graph` is left to mean the `acordia-analysts` document that `mcp-tool-surface`
  already names as the external consumer. Stating ownership without renaming would leave the URI
  exactly as ambiguous as the corpus found it.
- **Correct two stale consumer rationales in `mcp-tool-surface`.** The requirements at
  `openspec/specs/mcp-tool-surface/spec.md:13` and `:31` justify the published tool names by
  asserting that the skill falls back to raw HTTP when it cannot find them. The copy this repository
  ships forbids exactly that — it tells the analyst to stop and report — so the rationale asserts a
  fallback contract no shipped consumer is entitled to. The normative SHALLs do not change and remain
  justified by external consumers binding to these names generally; the unsafe-fallback assertion is
  removed. The corpus does record 3 raw-HTTP attempts against Aleph, all in one session, but those
  are a guardrail violation — or an older colliding copy of the skill — and are the reason this
  change strengthens the guardrail rather than evidence that the fallback is supported.

Not in scope: the `acordia-analysts` copy of the skill, which lives in another repository and needs
its own change; and remediation of the credential exposure found while measuring (a live Aleph API key was found in
plaintext in a session log; the locator is deliberately not recorded here), which is an operational action, not a code change.

## Capabilities

### New Capabilities

- `analyst-skill`: what the skill distributed with this plugin must contain and how it must be
  referenced — the call contract a leg reads first, the dispatch snippet that propagates it to
  subagents, query-precision guidance, outage-and-absence reporting discipline, the read-only
  guardrail, and a skill slug unique to this publisher. **BREAKING** for anyone referencing this
  plugin's skill as `aleph-entity-graph`.

### Modified Capabilities

- `mcp-tool-surface`: correct the recorded rationale under the published-tool-names and
  unprefixed-names requirements, which currently assert a raw-HTTP fallback behaviour the shipped
  skill forbids.

## Out of Scope

- Editing the `acordia-analysts` distribution of the same skill (separate repository, separate
  change).
- Any change to tool registration, argument validation, or server behaviour. Validation errors are
  already explicit — a caption-shaped `entity_id` and an out-of-range `limit` are each refused with
  a message naming the constraint — and the 54 outage failures are infrastructure that no guidance
  can prevent. What guidance changes is how a caller handles and reports an outage it cannot avoid.
- Rotating or redacting the exposed Aleph credential.
