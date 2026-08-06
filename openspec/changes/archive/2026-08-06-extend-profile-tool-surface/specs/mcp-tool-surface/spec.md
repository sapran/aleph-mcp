# mcp-tool-surface Specification

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: A profile-shaped entityset reports where the answer actually is

Aleph answers `GET /api/2/entitysets/<id>` with a `302` to the profile view when the addressed set is a profile, so `get_entityset` cannot return the curated-set record its name implies for that input. The tool SHALL detect the redirect, SHALL NOT follow it, and SHALL report `type: "profile"`, the same id, and a `_note` naming `get_profile` as the tool to use instead.

The redirect is not followed because Aleph builds its `Location` from the instance's configured public UI URL, which is a different origin from the API — see the `read-only-guard` capability, where the live evidence and the credential-stripping consequence are recorded. Reporting the redirect rather than chasing it also means this tool issues exactly one request per call.

#### Scenario: A profile id passed to the entityset tool is flagged

- **WHEN** `get_entityset` is called with the id of a profile-type set, and Aleph answers `302` toward the profile view
- **THEN** the response carries a `_note` stating that the set is a profile and naming `get_profile`

#### Scenario: An ordinary curated set carries no note

- **WHEN** `get_entityset` is called with the id of a list, diagram, or timeline set
- **THEN** the response carries the set's own record and no `_note`
