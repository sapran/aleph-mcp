## ADDED Requirements

### Requirement: An unusable instance model is refused, never cached as an empty ontology

The instance's FollowTheMoney model is read once from `GET /api/2/metadata` and cached for the process lifetime. A body whose `model` is present and not an object SHALL be refused where it would have been cached, with a message naming the JSON type that arrived, stating that the fault is upstream and that retrying will not help. The refusal SHALL quote nothing from the body.

A `model` that is absent, `null` or empty SHALL keep its existing meaning — an instance declaring no ontology — and SHALL be cached as an empty model.

An unusable model SHALL NOT be reported as an ontology that declares nothing: `list_schemata`, `get_schema` and the `aleph://schemata` resource SHALL surface the refusal, because for those the model is the answer and an empty answer would be a false statement about the instance. The entity-returning tools SHALL continue to degrade instead, deriving captions from the fixed fallback order, because a caption is a convenience and failing ten tools over it would be worse.

This requirement exists because the value was previously cached unchecked and read with `.get` outside any handler, so a `model` arriving as a string raised an `AttributeError` that reached the caller as a server defect, and — because the bad value was cached — left all ten shaped tools, both ontology tools and the ontology resource broken for the process lifetime.

#### Scenario: A non-object model degrades an entity-returning tool, and is announced

- **WHEN** `/api/2/metadata` answers `200` with `{"model": "https://example/model"}` and an entity-returning tool is called
- **THEN** the call answers, with captions derived from the fixed fallback order
- **AND** the reply's `_note` states the ontology could not be read
- **AND** no `AttributeError` reaches the caller

#### Scenario: An unusable model is not served as an empty ontology

- **WHEN** `/api/2/metadata` answers `200` with a `model` that is not an object and `list_schemata` is called
- **THEN** the call fails with a refusal naming the received JSON type
- **AND** the message states the fault is upstream and that retrying will not help
- **AND** it does not return a schema count of zero

#### Scenario: An absent model still means no ontology declared

- **WHEN** `/api/2/metadata` answers `200` with no `model` key
- **THEN** the model is cached as empty and no call is refused

### Requirement: A failing metadata route costs a bounded number of upstream requests

Failure to obtain a usable instance model SHALL be cached for a bounded window, during which the same failure is reported to a caller without issuing an upstream request. The window SHALL be bounded rather than permanent, so that a transient fault does not degrade every caption for the process lifetime, and it SHALL be measured on the same clock as this server's other budgets so that one patched clock governs all of them.

The failure reported from the cache SHALL be indistinguishable, in class and cause, from the failure that was cached, so that the read-only refusal this path can raise is still classified as one.

Only a success was memoised before this requirement: three entity-returning calls against a metadata route answering `503` were measured to cost twelve upstream requests — a full transport retry budget each — while still returning a degraded caption.

#### Scenario: Repeated calls inside the window pay one budget

- **WHEN** the metadata route fails and three entity-returning tools are called inside the window
- **THEN** the metadata route receives the requests of one retry budget in total

#### Scenario: The window expires

- **WHEN** the window has passed since the cached failure and an entity-returning tool is called
- **THEN** the metadata route is requested again

### Requirement: A caption derived because the ontology was unreadable says so

When a reply's captions were derived from the fixed fallback order *because* the instance ontology could not be read, the reply SHALL carry a `_note` stating that the ontology could not be read and that the captions are therefore derived rather than the instance's own. The note SHALL compose with any other note the reply carries rather than replacing it.

An ontology that was read successfully and declares no caption fields SHALL NOT produce this note: the fallback order is then the correct answer, not a degradation.

Every other degradation in this server announces itself — a truncated page, an empty slice, an unscoped search, a provenance-labelled value — while a fallback-derived caption was previously indistinguishable from one the instance's own ontology produced.

#### Scenario: An unreadable ontology is announced

- **WHEN** the metadata route fails and an entity-returning tool answers with captions
- **THEN** the reply carries a `_note` stating the ontology could not be read and the captions are derived

#### Scenario: An empty ontology is not a degradation

- **WHEN** the metadata route answers with a model whose `schemata` is an empty object
- **THEN** the reply carries no such note

#### Scenario: The note composes

- **WHEN** the metadata route fails and `search_entities` also reduces its page
- **THEN** the `_note` states both the reduced page and the unreadable ontology, neither replacing the other
