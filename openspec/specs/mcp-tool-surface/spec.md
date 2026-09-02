# mcp-tool-surface Specification

## Purpose

Defines the MCP surface this server publishes — which tools and resources exist, what a caller may rely on in their responses, and how they fail — so that consumers outside this repository can depend on it and so that drift is a spec change rather than a silent breakage.

## Requirements

### Requirement: The registered tool names are a published contract

The server SHALL register exactly these seventeen tools: `list_collections`, `get_collection`, `search_entities`, `get_entity`, `expand_entity`, `entity_tags`, `similar_entities`, `match_entity`, `get_profile`, `profile_tags`, `profile_similar`, `expand_profile`, `list_entitysets`, `get_entityset`, `entityset_items`, `xref_results`, `get_entity_text`.

These names are an external contract, not an implementation detail. The `aleph-entity-graph` skill distributed in the `acordia-analysts` plugin selects tools by name and, when it cannot find them, falls back to issuing raw HTTP requests under which the caller — not this server — becomes responsible for bounding results. Renaming or removing a tool therefore degrades a consumer this repository cannot edit, silently and without error, and SHALL be treated as a breaking change.

The four `profile_*`/`*_profile` tools and `get_profile` are named for the profile subsystem rather than the entity one because a profile is a distinct Aleph object — an EntitySet with a party, holding a recorded identity decision — and not a view of a single entity. `profile_similar` SHALL NOT be named `similar_profiles`: the endpoint returns entities similar to the profile, not similar profiles, and the plural form would assert the wrong return type.

#### Scenario: The seventeen tools are present

- **WHEN** the server is constructed and its registered tools are enumerated
- **THEN** the set of tool names is exactly the seventeen named above, with no additions and no omissions

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

This requirement binds every entity-shaped value in a response, not only the entities at the top level of a search result. In particular it binds `get_profile`'s `merged` field: a merged proxy inherits the properties of every entity in the profile, so a profile with a `Document` among its constituents carries that document's `bodyText` in `merged`. Passing `merged` through unslimmed would make this tool the one hole in the guarantee.

This is contractual rather than incidental: the `aleph-entity-graph` skill tells its analysts that these tools "strip document text out of search hits so it does not silently consume your context" and sets its reading method accordingly. Adding a new document-sized property to the set of stripped properties is a spec change under this requirement.

#### Scenario: Search hits are stripped

- **WHEN** `search_entities` returns a hit whose underlying Aleph entity carries any of `bodyText`, `bodyHtml`, `safeHtml`, `indexText`, or `translatedText`
- **THEN** those properties are absent from the returned entity
- **AND** each of them is listed in that entity's `_omitted_properties`

#### Scenario: Single-entity fetches are stripped identically

- **WHEN** `get_entity` returns an entity carrying any of those properties
- **THEN** the same stripping and the same `_omitted_properties` reporting apply

#### Scenario: A profile's merged entity is stripped identically

- **WHEN** `get_profile` returns a profile whose `merged` entity carries any of those properties, because a constituent entity of the profile is a document
- **THEN** those properties are absent from `merged`
- **AND** each of them is listed in `merged._omitted_properties`

#### Scenario: A profile response carries no transliteration block

- **WHEN** `get_profile` returns a profile for which Aleph's serializer emitted a `latinized` block, a transliteration of name values already present in `merged.properties`
- **THEN** that block is absent from the response, at the top level and inside `merged`

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

#### Scenario: A refused call costs no collection lookup

- **WHEN** a call that would be refused for its paging also names its collection by `foreign_id`, which normally costs a lookup to resolve
- **THEN** the paging refusal is raised first
- **AND** no request is sent to Aleph, the lookup included

### Requirement: An oversized search page is reduced, not discarded

When the upstream body for a `search_entities` call crosses the response ceiling this server decodes, the server SHALL re-issue the same query with a smaller page rather than failing the call, up to a bounded number of attempts. Each re-issue SHALL ask for strictly fewer rows than the attempt before it.

A response served this way SHALL carry `truncated: true` and `continue_from_offset` — the offset at which the caller resumes — and SHALL report `limit` as the page actually served rather than the page requested. `total` is unaffected, so paging still works. The response SHALL also state in its `_note` that the page was reduced and why, because a caller that reads only the rows cannot otherwise tell a short page from the end of a result set.

Both markers SHALL be withheld when the reduced page served no rows. `continue_from_offset` would then be the offset just used, so a caller obeying it repeats the identical request and pays the whole reduction again; an absent key is the honest signal, and the `_note` SHALL say that the query itself has to be narrowed. A reduction only ever lowers the row count, so a body made large by something other than its rows — the facet block, which does not vary with `limit` — is not rescued by it.

A result window this large is a paging problem, not an unanswerable query: in the run that prompted this requirement, a body 140 bytes over a 25 MiB ceiling discarded a result set whose caller only wanted counts. The ceiling itself is not relaxed — it bounds the allocation while the body streams, and a page is only ever made smaller, never larger, so the `limit + offset` window refusal above cannot be bypassed by this path.

The reduction SHALL be bounded rather than a search for the largest page that fits: each attempt is a whole extra request against Aleph, and the goal is a usable partial page.

#### Scenario: A page over the ceiling is re-asked smaller

- **WHEN** `search_entities` is called with a `limit` whose response exceeds the ceiling
- **THEN** the query is re-issued with a strictly smaller `limit`
- **AND** the response carries the rows that fit, `truncated: true`, and a `continue_from_offset` equal to `offset` plus the number of rows returned
- **AND** `limit` reports the page actually served

#### Scenario: A page that fits carries no marker

- **WHEN** the response fits under the ceiling
- **THEN** the response carries neither `truncated` nor `continue_from_offset`

#### Scenario: A single row over the ceiling is still refused

- **WHEN** the response exceeds the ceiling at a page of one, or at `limit=0`
- **THEN** the ceiling error is raised, because no page size can reduce it
- **AND** the query is not re-issued

#### Scenario: A shrunk page in an unenumerated result set reports both facts

- **WHEN** a page is reduced and the reported total also exceeds the 9999 result window
- **THEN** the `_note` states both that the page was truncated and that the result set is unenumerated, neither statement replacing the other

#### Scenario: A reduced page that served no rows offers nothing to resume

- **WHEN** the page is reduced but the successful attempt returns no rows, so that resuming at `offset` plus the row count would name the offset just used
- **THEN** the response carries neither `truncated` nor `continue_from_offset`
- **AND** the `_note` states that this offset yields nothing and that the query itself must be narrowed

### Requirement: Every search reports the schema scope it actually used

Aleph selects its search index from a schema filter and rejects a query carrying none. When the caller supplies neither `schema` nor `schemata`, the server SHALL apply the general scope `Thing` rather than failing, and SHALL report the scope actually searched under the response key `searched`.

The caller cannot otherwise distinguish "no matches" from "matched nothing within a scope I did not choose". This matters most for relationship schemata — `Ownership`, `Directorship`, `Payment`, `UnknownLink` — which do not descend from `Thing` and are therefore invisible unless named.

`searched` reports the collection scope alongside the schema scope, under the key `collection`. The two scenario titles below name only the schema scope, and assert their own key within `searched` rather than the whole of it, so that a later addition to that object does not falsify them.

#### Scenario: Default scope is applied and disclosed

- **WHEN** `search_entities` is called with neither `schema` nor `schemata`
- **THEN** the query is scoped to `schemata=Thing`
- **AND** the response reports `schemata` as `"Thing"` within `searched`

#### Scenario: An explicit exact schema is disclosed

- **WHEN** `search_entities` is called with `schema` set
- **THEN** no `schemata` scope is applied
- **AND** the response reports `schema` as the given value within `searched`, and no `schemata` key

### Requirement: A truncated expansion still reports its true degree

`expand_entity` returns at most 200 entities per property, a ceiling far lower than search's. Each returned property group SHALL carry a `count` reflecting the true number of adjacent entities, independent of how many were returned.

Without this a caller reads a capped group as a complete one and understates the degree of a node — the specific error that turns a hub entity into an apparently peripheral one.

#### Scenario: Capped group reports the real count

- **WHEN** an entity has more adjacent entities on a property than the returned group contains
- **THEN** that group's `count` is the true total, greater than the number of entities returned

### Requirement: A profile-shaped entityset reports where the answer actually is

Aleph answers `GET /api/2/entitysets/<id>` with a `302` to the profile view when the addressed set is a profile, so `get_entityset` cannot return the curated-set record its name implies for that input. The tool SHALL detect the redirect, SHALL NOT follow it, and SHALL report `type: "profile"`, the same id, and a `_note` naming `get_profile` as the tool to use instead.

The redirect is not followed because Aleph builds its `Location` from the instance's configured public UI URL, which is a different origin from the API — see the `read-only-guard` capability, where the live evidence and the credential-stripping consequence are recorded. Reporting the redirect rather than chasing it also means this tool issues exactly one request per call.

#### Scenario: A profile id passed to the entityset tool is flagged

- **WHEN** `get_entityset` is called with the id of a profile-type set, and Aleph answers `302` toward the profile view
- **THEN** the response carries a `_note` stating that the set is a profile and naming `get_profile`

#### Scenario: An ordinary curated set carries no note

- **WHEN** `get_entityset` is called with the id of a list, diagram, or timeline set
- **THEN** the response carries the set's own record and no `_note`

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

### Requirement: A search must name its collection scope

`search_entities` and `match_entity` SHALL require a `collection` argument and SHALL refuse any call that omits it. Searching every readable collection SHALL remain available only through the exact literal `"*"`.

Aleph answers an unscoped search successfully, so a caller that intended one collection and failed to say so receives another collection's rows with no error anywhere. Measured on a live run: the same query returned `total: 10000` with rows from collection `833` when the scope was lost, against `total: 5695` when it was applied. This server SHALL make that outcome unreachable by omission — a confidently incomplete or wrongly-sourced answer is a bug here, in the same way that clamped paging is.

The requirement is stated as a required argument rather than as a validated default so that the refusal is generated by the tool signature, ahead of any logic in this server, and cannot be bypassed by a code path added later. It exists because a host may silently drop an *unknown* argument before the call — verified for the omp `xd://` bridge — which makes any spelling this server does not itself declare unenforceable.

A value that names no collection SHALL be refused locally, before any request: the empty or blank string, the empty list, and `"*"` combined with named collections. A blank value is singled out because Aleph does not read it as naming nothing — it sanitises the filter away and answers `match_all`, so the listing returns whichever collection the key can read first. That is the same silent misdirection as an omitted scope, reached through a value that looks like an answer.

#### Scenario: An omitted scope is refused

- **WHEN** `search_entities` is called without `collection`
- **THEN** the call fails with an error naming the missing argument
- **AND** no request is sent to Aleph

#### Scenario: A single collection is applied

- **WHEN** `search_entities` is called with `collection` set to a numeric collection id
- **THEN** the query carries `filter:collection_id` for that id
- **AND** the response reports the resolved numeric ids as a list under `searched.collection` — here a single-element list; the literal `"*"` is the one non-list value that key takes

#### Scenario: Every collection must be asked for by name

- **WHEN** `search_entities` is called with `collection` set to `"*"`
- **THEN** no collection filter is applied
- **AND** the response reports `"*"` under `searched.collection`
- **AND** the `_note` states that the result spans every readable collection

#### Scenario: A scope naming nothing is refused without a request

- **WHEN** `search_entities` is called with `collection` set to an empty or blank string, to an empty list, or to a list containing `"*"` alongside named collections
- **THEN** the call raises a tool error naming what to pass instead
- **AND** no request is sent to Aleph

#### Scenario: A match against every collection is asked for by name

- **WHEN** `match_entity` is called with `collection` set to `"*"`
- **THEN** no collection constraint is sent to Aleph, which is its all-collections behaviour
- **AND** a `match_entity` call omitting `collection` fails with an error naming the missing argument

### Requirement: One vocabulary for collection scope across the tool surface

Every tool taking a collection SHALL name that argument `collection`, and SHALL accept a numeric collection id or a `foreign_id`. `search_entities` and `match_entity`, which search across collections, SHALL additionally accept a list of either. This applies to `get_collection`, `search_entities`, `match_entity`, `list_entitysets` and `xref_results`.

Three spellings for one concept — `collection`, `collection_id`, `collection_ids` — is what taught a caller to send `collection` to `search_entities`, where it was not declared. A model generalises the vocabulary a server teaches it on the neighbouring tool, so an inconsistent surface produces an argument that is plausible, wrong, and silently discarded by the host before this server can refuse it.

Accepting both id forms is part of the same requirement: a caller commonly holds a `foreign_id` and a numeric id for the same collection, and a tool that takes only one of them spends a turn on the conversion. A value of only digits is always read as a numeric id, so a collection whose `foreign_id` is itself all digits SHALL be addressed by its numeric id.

The three tools that address exactly one collection SHALL refuse `"*"` rather than looking it up as a foreign_id, because the same argument on the search tools uses that literal for every collection.

#### Scenario: A foreign_id is accepted wherever a numeric id is

- **WHEN** any collection-taking tool is called with a `foreign_id` instead of a numeric id
- **THEN** the foreign_id is resolved to its numeric id and the call proceeds
- **AND** a foreign_id that resolves to nothing raises an error naming `list_collections`

#### Scenario: A resolution is verified against what was asked for

- **WHEN** the collection listing answers a `foreign_id` lookup with a record whose own `foreign_id` is not the one requested
- **THEN** the call raises an error naming `list_collections` rather than searching the returned collection
- **AND** the rejected resolution is not cached

#### Scenario: A single-collection tool takes exactly one collection

- **WHEN** `get_collection`, `list_entitysets` or `xref_results` is called with a list, or with the literal `"*"`
- **THEN** the call is refused
- **AND** no request is sent to Aleph

#### Scenario: No tool exposes a differently-spelled collection argument

- **WHEN** the registered tool surface is inspected
- **THEN** no tool declares an argument named `collection_id` or `collection_ids`

#### Scenario: Resolving a scope cannot outrun the call's own budget

- **WHEN** `search_entities` or `match_entity` is called with a list naming more collections than one call may resolve
- **THEN** the call is refused before any request, naming the ceiling
- **AND** a scope that repeats a collection under two spellings resolves it once and emits one filter for it

### Requirement: A collection scope is stated once, not twice

`search_entities` SHALL refuse a call that passes a `collection_id` key inside `filters`, with an error naming the `collection` argument and the value to pass to it.

Merging the two spellings would keep both live, so the next caller learns whichever it happens to encounter and the ambiguity this requirement exists to remove survives inside its own fix. Every other `filters` key is unaffected: `filters` remains the general exact-match surface.

#### Scenario: A collection filter inside filters is refused

- **WHEN** `search_entities` is called with `filters` carrying a `collection_id` key
- **THEN** the call raises a tool error naming the `collection` argument
- **AND** no request is sent to Aleph
