## MODIFIED Requirements

### Requirement: The registered tool names are a published contract

The server SHALL register exactly these seventeen tools: `list_collections`, `get_collection`, `search_entities`, `get_entity`, `expand_entity`, `entity_tags`, `similar_entities`, `match_entity`, `get_profile`, `profile_tags`, `profile_similar`, `expand_profile`, `list_entitysets`, `get_entityset`, `entityset_items`, `xref_results`, `get_entity_text`.

These names are an external contract, not an implementation detail. Installed consumers select tools by name, both inside and outside this repository: the `aleph-mcp-entity-graph` skill shipped with this plugin, and the `aleph-entity-graph` skill distributed in the `acordia-analysts` plugin, which this repository cannot edit. Renaming or removing a tool degrades such a consumer silently and without error — an already-installed copy keeps naming the old tool whether or not its source can be updated — and SHALL therefore be treated as a breaking change.

No consumer is entitled to reach Aleph by another transport when a tool it expects is absent, and this requirement SHALL NOT be justified on the basis that one would: the skill distributed with this plugin requires the analyst to report the unavailability and stop, under the `analyst-skill` capability. A caller that issued its own HTTP requests instead would take on the bounding this server performs, which is why the behaviour is forbidden rather than accommodated.

The four `profile_*`/`*_profile` tools and `get_profile` are named for the profile subsystem rather than the entity one because a profile is a distinct Aleph object — an EntitySet with a party, holding a recorded identity decision — and not a view of a single entity. `profile_similar` SHALL NOT be named `similar_profiles`: the endpoint returns entities similar to the profile, not similar profiles, and the plural form would assert the wrong return type.

#### Scenario: The seventeen tools are present

- **WHEN** the server is constructed and its registered tools are enumerated
- **THEN** the set of tool names is exactly the seventeen named above, with no additions and no omissions

#### Scenario: A rename is caught before release

- **WHEN** a tool is renamed, removed, or added without this requirement being updated in the same change
- **THEN** the enumeration check fails, so the change cannot be merged as a non-breaking edit

### Requirement: Tool names are registered unprefixed

The server SHALL register tool names without a namespace prefix. Any prefix a caller observes — such as the `aleph_` prefix in `aleph_search_entities` — is applied by the host that mounts this server and is outside this server's control.

This is recorded because consumers outside this repository hardcode a prefixed form: the `aleph-entity-graph` skill in the `acordia-analysts` plugin does so, and the mount this plugin ships is observed as `mcp__aleph_mcp_<tool>`. This server SHALL NOT be held to guarantee any prefix, and SHALL NOT add one to compensate; the mount configuration is where that expectation is satisfied, and the skill distributed with this plugin SHALL state that the prefix belongs to the host rather than to the tool.

#### Scenario: Registered names carry no prefix

- **WHEN** the registered tool names are enumerated
- **THEN** none of them begins with `aleph_` or any other namespace prefix
