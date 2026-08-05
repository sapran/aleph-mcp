## MODIFIED Requirements

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
