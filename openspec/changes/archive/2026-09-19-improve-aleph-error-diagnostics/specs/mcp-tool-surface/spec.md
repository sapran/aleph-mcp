## ADDED Requirements

### Requirement: A retryable status reports the retry facts this server holds

An error raised for an upstream status this server treats as retryable SHALL state that the
status is retryable and how many upstream attempts were made.

It SHALL additionally report what the **final** response advertised as a next wait, and the
claim SHALL be scoped to that response. Where the final response carried a `Retry-After`
this server could parse, the message SHALL state that value normalised: parsed by this
server's one `Retry-After` parser and bounded by the retry sleep ceiling. The message SHALL
present it as what the response advertised, normalised — NOT as the wait this call would
have taken. The transport also clamps a wait by the call's remaining wall-clock budget, so
a terminal response advertising 30 s with 0.5 s of budget left would have produced a 0.5 s
sleep; reporting 30 s as an honoured wait would be false, and reporting 0.5 s would
misdescribe what the response asked for. The advertised-and-normalised value is the one
fact that is true of the response itself, independent of how much budget happened to
remain.
Where it carried the header in a form this server does not parse, the message SHALL say the
advertised wait was unusable, distinctly from its being absent. Where it carried no header,
the message SHALL say the final response advertised no next wait — never that no wait was
advertised at any point, which would be false whenever an earlier attempt advertised one
that was honoured.

The reported value SHALL be produced by the same `Retry-After` parser and the same sleep
ceiling the transport applies to that header, so that the number in the message is provably
the normalisation this server performs on what the response advertised. It SHALL NOT be
described as the wait the transport would have used, because the transport additionally
clamps by the call's remaining budget. It SHALL NOT echo the raw header text: the header is
untrusted upstream input, and the only safe report is the bounded number this server
derived from it.

It SHALL NOT classify the upstream condition from the text of the upstream body. The
observed `503` bodies carry an Elasticsearch cluster-state string; that text is not a
contract, and a caller's retry decision must not depend on upstream prose that can change
without notice. Absent a usable `Retry-After` this server cannot distinguish an initialising
index from a loaded one, so the facts are reported and the judgement stays with the caller.

This is required because a retryable refusal is otherwise indistinguishable from one that
never retried. Measured over a week of one consumer's traffic, 33 calls failed with `503`
— 24 `get_entity`, 8 `search_entities`, 1 `get_collection` — and every one reached the
generic final branch of `raise_for_status`, which reports the status and the upstream body
alone. The existing budget clause covers only the narrower case where the wall-clock
budget, rather than the retry count, ended the loop; a refusal that spent its full count
says nothing about having done so. The caller that reported this retried at 60-150 s
spacing, so the gap is not a retry storm but the difference between an honest coverage
statement and a silently incomplete sweep.

The facts SHALL be carried in the error text, because the error path this server raises
through serialises text only. A structured error field is not part of this change: MCP's
result type can carry structured content alongside an error flag, so such a field is
possible in principle and would be a deliberate extension of the published result contract
rather than a consequence of this one.

#### Scenario: A final response advertising no wait

- **WHEN** an upstream response carries a retryable status and no `Retry-After` header, and the retry budget is exhausted
- **THEN** the error states that the status is retryable
- **AND** it states how many attempts were made
- **AND** it states that the final response advertised no next wait
- **AND** it does not state a wait value

#### Scenario: A final response advertising a usable wait

- **WHEN** the final upstream response carries a `Retry-After` this server can parse
- **THEN** the error states that value normalised by this server's parser and sleep ceiling
- **AND** it does not present the value as the wait this call would have taken

#### Scenario: An advertised wait beyond the ceiling is normalised, not echoed

- **WHEN** the final response advertises a wait larger than the transport's maximum sleep
- **THEN** the reported value is the sleep ceiling, not the header value
- **AND** the raw header text is not echoed

#### Scenario: A narrow remaining budget does not change the reported value

- **WHEN** the final response advertises a wait larger than the call's remaining wall-clock budget
- **THEN** the reported value is the advertised value normalised by the sleep ceiling alone
- **AND** the message does not claim this call would have waited that long

#### Scenario: An unparseable wait is distinguished from an absent one

- **WHEN** the final response carries a `Retry-After` in a form this server does not parse
- **THEN** the error says the advertised wait was unusable
- **AND** it does not say the response advertised no wait

#### Scenario: An earlier advertised wait does not make the final claim false

- **WHEN** an earlier attempt's response advertised a wait that was honoured and the final response carries no header
- **THEN** the error's claim is limited to the final response
- **AND** it does not assert that no wait was advertised during the call

#### Scenario: A non-retryable status reports no retry facts

- **WHEN** an upstream response carries a status outside the retried set
- **THEN** the error states neither an attempt count nor a retryability claim

#### Scenario: The upstream body does not drive the classification

- **WHEN** a retryable status carries an upstream body describing the condition in its own words
- **THEN** the retryability stated by the error is decided by the status alone
- **AND** the error does not restate that body as a classification

## MODIFIED Requirements

### Requirement: Invalid arguments surface as tool and resource errors

Every tool SHALL translate an argument-validation failure into an MCP tool error carrying the reason. Every resource SHALL translate the same failure into an MCP resource error. A caller SHALL NOT receive a transport-level or unhandled exception in place of a validation message.

Validation SHALL be anchored so that no trailing character escapes it, and SHALL reject an id that carries no addressable content. Every path segment interpolated from a caller-supplied value SHALL pass a validator before the request is constructed; no method may match an id inline and skip the shared check.

An identifier refused for its character set SHALL additionally name the reply field a valid identifier is read from, and that clause SHALL be a constant of the field being validated — `entity_id`, `profile_id` or `entityset_id` — not an inference from the rejected value. The accepted character set, the echo of the rejected value, and every refusal decision SHALL be unchanged: this adds a clause to a message and loosens no validation.

This is required because the refusal is correct and unhelpful. Measured over a week of one consumer's traffic, 9 calls passed a rendered property label where an identifier belongs — `'Email 1.2'`, `'Pages 1.1'` — and the message named only the accepted charset, never where a real identifier comes from. An independent audit of a second corpus found the same class, so the failure is not particular to one consumer. The clause is unconditional rather than triggered by a shape test, because a "looks like a label" classifier would miss other rendered labels while changing nothing about what is accepted.

A refusal this server makes on its own judgement SHALL be a distinct exception type, raised only at
the sites that make such a refusal, and the tool and resource seams SHALL translate that type
rather than a category of Python failure. Any other exception raised inside a tool or resource body
SHALL NOT be presented to the caller as a refusal. The distinction the type draws is *authored
rather than escaped* -- a message this server composed and meant the caller to read -- and NOT
*caller-fixable*: several refusals correctly tell the caller the fault is upstream and that
retrying will not help, and those must still reach the model unwrapped. What must never be
presented as a refusal is an exception nobody here composed, because its text was written for a
Python traceback rather than for the caller, and reading it as this server's considered answer
directs the caller to rewrite arguments that were never the cause. Measured on
`develop @ 7f9c139`, where the seam selected on `ValueError`: a `200` carrying an HTML maintenance
page reached the model as `Expecting value: line 1 column 1 (char 0)` and a tool body calling
`int()` on upstream text as `invalid literal for int() with base 10: 'not-a-number'` — both
unprefixed and both surviving `mask_error_details`, which is the shape reserved for a deliberate
refusal.

The refusal type SHALL remain a subclass of `ValueError`, which is what this client's refusals have
always been, so that a library caller catching `ValueError` around a client call keeps catching
them.

#### Scenario: Invalid entity id from a tool

- **WHEN** a tool is called with an `entity_id` outside the accepted character set
- **THEN** it raises a tool error whose message states the accepted form and echoes the rejected value
- **AND** the message names the reply field a valid `entity_id` is read from

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

#### Scenario: A failure that is not a refusal is not dressed as one

- **WHEN** a tool or resource body raises a `ValueError` that this server did not raise as a refusal — an `int()` on upstream text, a nested `json.loads`, a `datetime.fromisoformat`
- **THEN** the seam does not translate it, so it reaches the caller as the server fault it is rather than as a message telling the caller to change its arguments

#### Scenario: A refusal is catchable by type from a library caller

- **WHEN** `AlephClient` is used directly and a call is refused for a bad argument
- **THEN** the refusal is an instance of the dedicated refusal type
- **AND** it is still an instance of `ValueError`

#### Scenario: Each validated identifier field names its own source

- **WHEN** `profile_id` and `entityset_id` are each refused for their character set
- **THEN** each message names the reply field that identifier is read from
- **AND** neither names the source belonging to another field

#### Scenario: The source clause does not depend on the rejected value

- **WHEN** two values outside the accepted set are refused for the same field, one resembling a rendered label and one not
- **THEN** both messages carry the same source clause
