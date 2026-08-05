# mcp-tool-surface Specification

## Purpose

Defines the MCP surface this server publishes — which tools and resources exist, what a caller may rely on in their responses, and how they fail — so that consumers outside this repository can depend on it and so that drift is a spec change rather than a silent breakage.

## Requirements

### Requirement: The registered tool names are a published contract

The server SHALL register exactly these twelve tools: `list_collections`, `get_collection`, `search_entities`, `get_entity`, `expand_entity`, `entity_tags`, `similar_entities`, `match_entity`, `list_entitysets`, `entityset_items`, `xref_results`, `get_entity_text`.

These names are an external contract, not an implementation detail. The `aleph-entity-graph` skill distributed in the `acordia-analysts` plugin selects tools by name and, when it cannot find them, falls back to issuing raw HTTP requests under which the caller — not this server — becomes responsible for bounding results. Renaming or removing a tool therefore degrades a consumer this repository cannot edit, silently and without error, and SHALL be treated as a breaking change.

#### Scenario: The twelve tools are present

- **WHEN** the server is constructed and its registered tools are enumerated
- **THEN** the set of tool names is exactly the twelve named above, with no additions and no omissions

#### Scenario: A rename is caught before release

- **WHEN** a tool is renamed, removed, or added without this requirement being updated in the same change
- **THEN** the enumeration check fails, so the change cannot be merged as a non-breaking edit

### Requirement: Tool names are registered unprefixed

The server SHALL register tool names without a namespace prefix. Any prefix a caller observes — such as the `aleph_` prefix in `aleph_search_entities` — is applied by the host that mounts this server and is outside this server's control.

This is recorded because the `aleph-entity-graph` consumer hardcodes the prefixed form. This server SHALL NOT be held to guarantee that prefix, and SHALL NOT add one to compensate; the mount configuration is where that expectation is satisfied.

#### Scenario: Registered names carry no prefix

- **WHEN** the registered tool names are enumerated
- **THEN** none of them begins with `aleph_` or any other namespace prefix

### Requirement: The resource surface is a published contract

The server SHALL expose exactly three resources: `aleph://collections`, `aleph://schemata`, and the templated `aleph://schema/{name}`, each serving `application/json`.

#### Scenario: The three resources are present

- **WHEN** the server's registered resources and resource templates are enumerated
- **THEN** exactly those three URIs are present, and each declares mime type `application/json`

### Requirement: No tool response carries document-sized text

No entity returned by any tool SHALL carry a document-sized text property. When such a property is dropped from an entity, the entity SHALL name every dropped property, sorted, under the key `_omitted_properties`, so the caller can tell the difference between a property that was absent and one that was withheld.

`get_entity_text` is the sole path to a document body, and it is bounded by its own `offset`/`limit` arguments.

This is contractual rather than incidental: the `aleph-entity-graph` skill tells its analysts that these tools "strip document text out of search hits so it does not silently consume your context" and sets its reading method accordingly. Adding a new document-sized property to the set of stripped properties is a spec change under this requirement.

#### Scenario: Search hits are stripped

- **WHEN** `search_entities` returns a hit whose underlying Aleph entity carries any of `bodyText`, `bodyHtml`, `safeHtml`, `indexText`, or `translatedText`
- **THEN** those properties are absent from the returned entity
- **AND** each of them is listed in that entity's `_omitted_properties`

#### Scenario: Single-entity fetches are stripped identically

- **WHEN** `get_entity` returns an entity carrying any of those properties
- **THEN** the same stripping and the same `_omitted_properties` reporting apply

#### Scenario: Nothing dropped means no marker

- **WHEN** a returned entity carries none of those properties
- **THEN** the response contains no `_omitted_properties` key

#### Scenario: Document text remains reachable deliberately

- **WHEN** the caller needs the body that was withheld
- **THEN** `get_entity_text` returns a bounded slice of it, reporting `total_chars`, `returned_chars`, and `truncated`

### Requirement: Unreachable result sets are refused, not silently truncated

`search_entities` SHALL refuse any request whose `limit + offset` exceeds Aleph's result window of 9999, raising a tool error that states the limit and directs the caller to narrow by filter or facet.

Aleph itself clamps such a request and answers successfully, which leads a caller to believe it paged to the end of a result set it never saw. This server SHALL fail loudly instead. Paging is not a supported way to enumerate a large collection.

#### Scenario: Over-window request is refused

- **WHEN** `search_entities` is called with `limit + offset` greater than 9999
- **THEN** the call raises a tool error naming the 9999 ceiling
- **AND** no request is sent to Aleph

#### Scenario: A total beyond the window is marked unenumerated

- **WHEN** a search succeeds but the reported total exceeds 9999
- **THEN** the response carries a `_note` stating the result set is unenumerated rather than merely long, and that the total is a lower bound

#### Scenario: Negative paging is refused

- **WHEN** `search_entities` is called with a negative `limit` or a negative `offset`
- **THEN** the call raises a tool error and no request is sent to Aleph

### Requirement: Every search reports the schema scope it actually used

Aleph selects its search index from a schema filter and rejects a query carrying none. When the caller supplies neither `schema` nor `schemata`, the server SHALL apply the general scope `Thing` rather than failing, and SHALL report the scope actually searched under the response key `searched`.

The caller cannot otherwise distinguish "no matches" from "matched nothing within a scope I did not choose". This matters most for relationship schemata — `Ownership`, `Directorship`, `Payment`, `UnknownLink` — which do not descend from `Thing` and are therefore invisible unless named.

#### Scenario: Default scope is applied and disclosed

- **WHEN** `search_entities` is called with neither `schema` nor `schemata`
- **THEN** the query is scoped to `schemata=Thing`
- **AND** the response reports `searched` as `{"schemata": "Thing"}`

#### Scenario: An explicit exact schema is disclosed

- **WHEN** `search_entities` is called with `schema` set
- **THEN** no `schemata` scope is applied
- **AND** the response reports `searched` as `{"schema": "<value>"}`

### Requirement: A truncated expansion still reports its true degree

`expand_entity` returns at most 200 entities per property, a ceiling far lower than search's. Each returned property group SHALL carry a `count` reflecting the true number of adjacent entities, independent of how many were returned.

Without this a caller reads a capped group as a complete one and understates the degree of a node — the specific error that turns a hub entity into an apparently peripheral one.

#### Scenario: Capped group reports the real count

- **WHEN** an entity has more adjacent entities on a property than the returned group contains
- **THEN** that group's `count` is the true total, greater than the number of entities returned

### Requirement: Invalid arguments surface as tool and resource errors

Every tool SHALL translate an argument-validation failure into an MCP tool error carrying the reason. Every resource SHALL translate the same failure into an MCP resource error. A caller SHALL NOT receive a transport-level or unhandled exception in place of a validation message.

Validation SHALL be anchored so that no trailing character escapes it, and SHALL reject an id that carries no addressable content. Every path segment interpolated from a caller-supplied value SHALL pass a validator before the request is constructed; no method may match an id inline and skip the shared check.

#### Scenario: Invalid entity id from a tool

- **WHEN** a tool is called with an `entity_id` outside the accepted character set
- **THEN** it raises a tool error whose message states the accepted form and echoes the rejected value

#### Scenario: Invalid schema name from a resource

- **WHEN** `aleph://schema/{name}` is read with a name the instance does not define
- **THEN** it raises a resource error, not an unhandled exception

#### Scenario: Out-of-range text slice

- **WHEN** `get_entity_text` is called with a negative `offset`, or a `limit` outside 1..200000
- **THEN** it raises a tool error stating the accepted range

#### Scenario: Trailing whitespace does not escape validation

- **WHEN** a tool is called with an id whose only invalid character is a trailing newline or carriage return, such as `"e1\n"`
- **THEN** it raises a tool error stating the accepted id form
- **AND** the message is the validator's, not the HTTP layer's

#### Scenario: An id of only dot segments is refused

- **WHEN** a tool is called with an id consisting solely of dot segments, such as `".."` or `"."`
- **THEN** it raises a tool error stating the accepted id form
- **AND** no request is sent, so the caller cannot be answered from a different endpoint than the one addressed

#### Scenario: Numeric collection ids are validated on every path

- **WHEN** `get_collection` is called with a value that looks numeric but carries a trailing newline
- **THEN** it raises a tool error from the shared collection-id validator
- **AND** no request is sent to Aleph
