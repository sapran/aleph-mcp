## ADDED Requirements

### Requirement: Ontology text quoted back to the caller is bounded and neutralised

The FollowTheMoney schema names this server reads from the instance metadata route are
upstream text: whoever runs the Aleph instance, or proxies it, chooses them. Wherever such a
name is quoted back into a model-visible message, the server SHALL bound its length and SHALL
substitute characters that are not printable, rendering the substitution visibly rather than
dropping it.

This is the same rule this server already applies to property values, collection echoes,
request targets and upstream error text; the ontology is a context it did not previously
cover. It matters here because a schema-name refusal leaves through `aleph://schema/{name}`
unprefixed, which is the shape reserved for a caller-actionable message and which therefore
survives error masking: an un-neutralised name can close a quoted region, reorder the line with
a bidirectional override, or emit terminal control sequences into a client that renders the
refusal, and an unbounded one is a write primitive into the model's context.

A refusal that suggests near-matching schema names SHALL bound the suggestion list by its total
rendered length, not only by the number of names it offers, so that the per-name bound cannot be
defeated by offering many names at once.

#### Scenario: A hostile schema name is neutralised in a refusal

- **WHEN** the instance ontology declares a schema name containing control, format or
  bidirectional-override characters, and `get_schema` is called with a name that does not exist
  but shares that name's opening characters
- **THEN** the refusal names the near match with every non-printable character replaced by a
  visible substitution
- **AND** no control, format or bidirectional-override character from the upstream name appears
  in the message

#### Scenario: An oversized schema name cannot inflate a refusal

- **WHEN** the instance ontology declares a schema name of 20,000 characters and `get_schema` is
  called with a name that does not exist but shares its opening characters
- **THEN** the refusal is bounded to a length that holds a short sentence and its suggestions,
  not the upstream name

#### Scenario: Many near matches cannot together restore the unbounded echo

- **WHEN** the instance ontology declares many schema names sharing the queried prefix, each at
  the per-name bound
- **THEN** the suggestion list is cut at the total-length bound, offering fewer names rather
  than a longer message
- **AND** at least one suggestion is still offered

#### Scenario: An ordinary near match is unchanged

- **WHEN** the instance ontology is a normal FollowTheMoney ontology and `get_schema` is called
  with a misspelling of a real schema name
- **THEN** the suggestions are the real schema names, character for character

### Requirement: The schema listing is bounded, labelled and announces its own truncation

The `aleph://schemata` resource SHALL bound the number of schema names it returns and SHALL
render each name under the same bound and substitution as a name quoted into a refusal. When the
instance declares more names than the bound admits, the resource SHALL report how many were
omitted rather than returning a silently short list: a confidently incomplete answer is a defect
here, and the resource's `count` is the instance's own total, not the length of the list served.

The resource SHALL carry a `_provenance` label marking the names as upstream-authored, matching
the labelling this server already applies to aggregated facet values and to document text. The
`aleph-entity-graph` skill distributed in the `acordia-analysts` plugin reads this resource to
choose schema filters, so both keys are additive on an object it already parses.

#### Scenario: An oversized schema name does not reach the listing whole

- **WHEN** the instance ontology declares a schema name far longer than the per-name bound and
  `aleph://schemata` is read
- **THEN** the served name is bounded, and the response is not sized by the upstream name

#### Scenario: A listing longer than the bound says what it dropped

- **WHEN** the instance ontology declares more schema names than the listing bound admits
- **THEN** the response reports, for each list it bounded, how many names that list omitted
- **AND** `count` still reports the instance's own total, not the length of the list served

#### Scenario: An ordinary ontology is served in full and labelled

- **WHEN** the instance ontology is a normal FollowTheMoney ontology and `aleph://schemata` is
  read
- **THEN** every declared name is served unchanged
- **AND** the response carries a `_provenance` label stating that the names come from the Aleph
  instance rather than from this server
- **AND** the response reports no omissions
