# analyst-skill Specification

## Purpose
Defines the analyst method skill this plugin distributes alongside its MCP server — what it must
contain, under what name it is published, and how an orchestrating agent hands it to the subagents
that actually issue the calls — so that guidance shipped with the tools reaches the caller instead
of being retyped, shadowed by another publisher, or silently missed.

## Requirements

### Requirement: The distributed skill is published under a slug unique to this plugin

The skill this plugin distributes SHALL be published under the slug `aleph-mcp-entity-graph`, and
SHALL NOT be published under `aleph-entity-graph`.

The `acordia-analysts` plugin — an out-of-repo consumer this repository cannot edit, and the
consumer already named in the `mcp-tool-surface` capability — publishes a different document under
`aleph-entity-graph`. When both plugins are installed, a `skill://aleph-entity-graph` reference is
satisfied by whichever of the two the host resolves — a selection neither document controls, and
one that has historically returned three different documents in this profile — so the reference
does not identify a document. A unique slug is therefore a correctness property of the reference,
not a naming preference.

Every `skill://` reference to this plugin's own skill that this repository ships — in its README,
its plugin manifest, its marketplace entry, and the dispatch snippet required below — SHALL name
the unique slug.

#### Scenario: The published slug is unique

- **WHEN** the skills this plugin distributes are enumerated
- **THEN** the skill directory and its frontmatter `name` are `aleph-mcp-entity-graph`, and no
  skill named `aleph-entity-graph` is published by this plugin

#### Scenario: No shipped reference names the ambiguous slug

- **WHEN** this repository's shipped documentation and manifests are searched for `skill://`
  references to its own analyst skill
- **THEN** every such reference names `aleph-mcp-entity-graph`

### Requirement: The skill opens with the mechanical call contract

The skill SHALL state, before any doctrine or method narrative, the mechanical facts a caller needs
to issue a first correct call:

- the argument name for an entity identifier is `entity_id`, never `id` or `entity`;
- an identifier is taken from a result's `id` field and never from a `caption` or other display
  string;
- `schema` and `schemata` are top-level arguments and SHALL NOT be passed as `filters` keys, and
  `collection_id` SHALL NOT be passed in `filters` at all;
- `collection` is required on `search_entities` and `match_entity`;
- the invocation mechanism belongs to the host and SHALL be established from the mounted tool
  schema before the first call, not assumed: a host that exposes these tools as devices takes a
  JSON object written to the device and returns the schema on request, while a host that exposes
  them as direct tool calls is invoked normally.

This ordering is required because the corpus of real use shows a caller reads the opening of the
document and acts. Of 29 identifier-handling failures across 8 sessions, 22 were exactly the
mistakes the facts above prevent — 12 calls naming the argument `id` or `entity`, and 10 passing a
display caption where an identifier belongs — each of which the prior document stated only in later
prose or not at all. The remaining 7 were `404`s whose cause the corpus does not establish, and
are not attributed to these facts.

#### Scenario: A caller can issue a correct identifier call from the opening section

- **WHEN** the skill is read from its start until the end of its call-contract section
- **THEN** that text states the `entity_id` argument name, the rule that an identifier comes from a
  result's `id` field, the top-level placement of `schema`/`schemata`, and the requirement that
  `collection` accompanies a `search_entities` or `match_entity` call

#### Scenario: The invocation mechanism is not assumed

- **WHEN** the call-contract section's guidance on how a call is issued is read
- **THEN** it directs the caller to establish the mechanism from the mounted tool schema, and
  describes the device-written form as one host's mechanism rather than as the only one

### Requirement: The skill carries a dispatch snippet for delegating work

The skill SHALL contain a snippet, marked for verbatim reuse, that an orchestrating agent includes
in a subagent assignment to direct that subagent to read the skill before its first Aleph call.

This exists because guidance that only the orchestrator reads does not govern the calls: in the
measured corpus, 740 of the 1,349 Aleph calls made in the 37 sessions issuing five or more came
from subagent legs that had read no Aleph skill, while orchestrators restated the skill's rules by
hand in all 30 dispatches that mentioned Aleph.

#### Scenario: The snippet is present and self-contained

- **WHEN** the skill is read
- **THEN** it contains a quotable dispatch snippet that names the skill by its unique slug and
  instructs the recipient to read it before issuing an Aleph call, requiring no other text from the
  skill to be understood

### Requirement: The skill requires failed calls to be reported in the coverage statement

The skill SHALL require that a coverage statement name the calls that failed, and SHALL require
that an empty result be reported as an empty result under a stated scope rather than as absence of
the thing sought.

It SHALL distinguish, as reportable outcomes, an upstream service failure from a result of zero
rows, and SHALL state that a service failure suspends the conclusion rather than supporting a
negative one.

This is required because a degraded run otherwise produces a confident deliverable: in the measured
corpus one leg failed 21 of its 32 calls to an upstream `503`, correctly diagnosed the outage in its
own narrative, and still closed by reporting its register as coherent, final and complete.

#### Scenario: Coverage discipline is stated

- **WHEN** the skill's reporting guidance is read
- **THEN** it requires failed calls to appear in the coverage statement, and requires an empty
  result to be attributed to the scope searched rather than reported as absence

#### Scenario: An outage is not reportable as absence

- **WHEN** the skill's guidance for an upstream service failure is read
- **THEN** it states that the failure suspends the conclusion and SHALL NOT be reported as evidence
  that the thing sought is not present

### Requirement: The skill refuses a raw-HTTP fallback

When the tools are not available to it, the skill SHALL direct the analyst to report their
unavailability and stop, and SHALL NOT offer, describe, or condone reaching Aleph by any other
transport.

The refusal is the point: any other transport puts a credential-bearing client in the caller's hands
with none of the controls this server enforces, and material read from Aleph can carry instructions
aimed at the caller, so a rule that can be argued away is not a control. The measured corpus records
3 such attempts in one session, including a request that placed the API key inline in a shell
command.

#### Scenario: Unavailable tools stop the work

- **WHEN** the skill's guidance for the case where its tools are not mounted is read
- **THEN** it directs the analyst to report the unavailability and stop, and offers no alternative
  transport

#### Scenario: The Aleph credential never materialises in a call, a command or a log

- **WHEN** the skill's guardrails are read
- **THEN** they forbid the Aleph API credential from appearing in a tool argument, a shell command,
  a constructed request, or a log line

#### Scenario: Credential material found in the corpus is pivoted only through the tools

- **WHEN** the skill's guardrails for credential material discovered inside corpus content are read
- **THEN** they permit pivoting on that material through the server's own search and pivot tools —
  a reuse check being the named case — while forbidding it in a raw HTTP request or a shell command,
  and they restrict what reaches a report to classification, identifiers and provenance rather than
  the value

### Requirement: Query precision is stated as exact filters and quoted phrases

The skill SHALL state that precision comes from exact `filters` and quoted phrases, and SHALL state
that adding bare terms to `q` widens a result set rather than narrowing it, because a multi-term
query requires only 66% of its terms to match.

It SHALL keep the facet-first survey — a `limit=0` request carrying `facets` before any rows are
pulled — as the step that precedes narrowing.

This is required because the measured corpus shows the two rules landing very differently. Across
the 887 searches whose JSON body parsed: 649 carried `facets` and 29 of 35 searching sessions
faceted at least once, while `filters` appeared in 7 (0.8%) and 78 (8.8%) were unquoted
multi-term `q`. The facet rule is concrete and was followed; the precision rule was stated as an
adverb and was not.

#### Scenario: The precision route is named

- **WHEN** the skill's query guidance is read
- **THEN** it names exact `filters` and quoted phrases as the route to precision, and states that
  adding bare terms to `q` widens the result set because only 66% of its terms must match

#### Scenario: Facet-first survives the change

- **WHEN** the skill's query guidance is read
- **THEN** it still requires a `limit=0` faceted survey before rows are pulled

### Requirement: Profile guidance is trigger-loaded rather than inlined

The profile guidance — `get_profile`, `profile_tags`, `profile_similar` and `expand_profile` — SHALL
be held in a reference file rather than in the primary method text, and the method text SHALL name
the observable trigger under which it is to be read: a reply carrying a `profile_id`.

The evidence is specific to this subsystem: `profile_id` was absent — neither
populated nor null — from all 1,356 tool replies and all 809 spilled result payloads in the
measured corpus, while every one of those 809 payloads did carry the ordinary entity fields
`schema` and `caption` — which is what makes the zero an absence rather than an artefact. The
server forwards `profile_id` whenever Aleph supplies it, so the guidance is correct and simply
unreachable on that instance. It is demoted rather than deleted because an instance with curated
profiles makes it load-bearing again.

Entity-set and cross-reference guidance SHALL remain in the primary method text. `list_entitysets`
was called 8 times in the measured window without error, an entity set does not depend on a
profile, and no observed trigger gates it — so demoting it would move reachable guidance out of
reach on the strength of evidence that concerns a different subsystem.

#### Scenario: Profile guidance is reachable by trigger, not by default

- **WHEN** the skill's primary method text is read
- **THEN** the profile guidance is not inlined there, and the method text names the observable
  trigger — a reply carrying a `profile_id` — under which the reference file is to be read

#### Scenario: Entity-set guidance stays in the primary method

- **WHEN** the skill's primary method text is read
- **THEN** the guidance for `list_entitysets`, `get_entityset`, `entityset_items` and `xref_results`
  is present there and is not held behind a `profile_id` trigger
