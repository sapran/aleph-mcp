# read-only-guard Specification

## Purpose

Defines what this server refuses to send to Aleph, on every request and every redirect hop, so that the read-only claim is a stated and tested boundary rather than a property of the current code, and so that the edges of that claim are visible to anyone auditing it.

## Requirements

### Requirement: Only allowlisted method and path pairs are sent

The server SHALL refuse any outgoing request whose HTTP method and API-relative path do not both match a fixed allowlist of Aleph read endpoints. Refusal SHALL happen before the request is transmitted, and SHALL NOT depend on what the configured API key is permitted to do server-side.

The allowlist SHALL be the only mechanism that widens the reachable surface. No tool argument, no resource template, no configuration value and no server response SHALL be able to add a reachable endpoint.

The method half of each pair is load-bearing and SHALL NOT be treated as redundant with the path half. Two allowlisted GET paths are also live Aleph write routes, and the absence of a matching pair is the only thing that refuses them:

- `/api/2/entitysets/<id>` is allowlisted for `GET`, and upstream Aleph registers `DELETE`, `POST` and `PUT` on that identical path (`aleph/views/entitysets_api.py:144,181`). This is not a pattern accident — the same path is both a read and a write route, distinguished by method alone.
- `POST /api/2/profiles/_pairwise` is matched by the allowlisted rule for `GET /api/2/profiles/<id>`, because the accepted id character class includes `_`. It records a judgement and can create or merge a profile (`aleph/views/profiles_api.py:207`).

Consequently a reviewer SHALL NOT infer that a path rule is safe because its read is, and a pair SHALL NOT be reduced to a path.

The id character class SHALL NOT be narrowed to hexadecimal in order to exclude `_pairwise` by path. Aleph ids are only conventionally `uuid4().hex`; the underlying column is a 128-character string, so a narrowed pattern would refuse legitimate ids on any instance that ever minted one differently, converting a safety margin into an availability bug.

#### Scenario: A mutating request is refused before transmission

- **WHEN** any code path attempts a request whose method and path are not in the allowlist, such as `POST /api/2/collections/42/reingest`
- **THEN** the request is refused with an error naming the blocked method and URL
- **AND** no HTTP request reaches the network

#### Scenario: A read-shaped path outside the allowlist is refused

- **WHEN** a request targets a path that resembles an allowlisted one but is not, such as `GET /api/2/entities/e1/delete`
- **THEN** it is refused

#### Scenario: A write whose path matches an allowlisted GET is refused on its method

- **WHEN** `DELETE`, `POST` or `PUT` is attempted against `/api/2/entitysets/<id>`, a path allowlisted for `GET` on which Aleph also routes those three methods
- **THEN** each is refused, because no allowlist pair carries both that method and that path
- **AND** `GET` against the same path remains allowed, so the refusal is attributable to the method pin alone

#### Scenario: A write reachable only through the id charset is refused

- **WHEN** `POST /api/2/profiles/_pairwise` is attempted, a path that the allowlisted `GET /api/2/profiles/<id>` rule matches because the id character class admits `_`
- **THEN** it is refused on its method
- **AND** `GET` against that same path remains allowed, confirming the path rule alone would not have refused it

#### Scenario: The allowlist carries no mutating verb

- **WHEN** the allowlist is enumerated
- **THEN** every entry is a `GET`, except a single `POST /api/2/match`, which is a lookup that carries its query in a body

### Requirement: Requests that leave the configured origin or base path are refused

The server SHALL refuse any request whose origin — scheme, host and port, with the scheme's default port resolved — differs from the configured Aleph origin, and any request whose path does not fall under the configured base path. The configured base path SHALL be stripped before the allowlist is matched, so an Aleph mounted under a sub-path is checked on its API-relative path like any other.

This exists because an Aleph instance can redirect, and the body of a `POST /api/2/match` would otherwise be re-sent to the redirect target. The pin is the whole origin rather than the hostname because a hostname comparison admits a redirect that downgrades `https` to `http`, or that points at a different service on another port of the same machine.

#### Scenario: Cross-host redirect is refused and no credential is emitted

- **WHEN** an allowlisted request receives a redirect to a host other than the configured one
- **THEN** the redirected request is refused
- **AND** the `Authorization` header is never sent to that host

#### Scenario: A redirect keeping the hostname but changing scheme or port is refused

- **WHEN** a redirect targets the configured hostname on `http` instead of `https`, or on a port other than the configured one
- **THEN** the request is refused before the allowlist is consulted
- **AND** naming the scheme's default port explicitly is the same origin, so the instance's own canonical redirect is still allowed

#### Scenario: A sub-path mount is matched on its API-relative path

- **WHEN** the configured host includes a base path, such as `https://example.org/aleph`
- **THEN** a request to `https://example.org/aleph/api/2/entities` is matched as `/api/2/entities` and allowed
- **AND** a request to the same host outside that base path is refused

### Requirement: The guard applies to every redirect hop

The refusal SHALL be evaluated for each request the transport issues, including every hop of a redirect chain, not only the request the caller originated.

#### Scenario: A redirect chain ending at a write is refused at the final hop

- **WHEN** an allowlisted request redirects to another allowlisted request, which redirects to a mutating endpoint
- **THEN** the guard evaluates all three requests
- **AND** the mutating endpoint is never called

#### Scenario: A method-and-body-preserving redirect cannot replay a body into a write

- **WHEN** `POST /api/2/match` receives a 307 redirect to a mutating endpoint on the same host
- **THEN** the redirected request is refused and the body is not replayed

### Requirement: An Aleph redirect is not assumed to stay on the API

Aleph builds redirect `Location` headers from its configured **public UI URL**, which on a real deployment is a different host and port from the API the client is connected to. A redirect SHALL therefore NOT be assumed to land on the Aleph API, and a tool SHALL NOT depend on following one to produce its result.

This was verified against a live instance: `GET /api/2/entitysets/<id>` for a profile-type set returned `302` with `Location: http://localhost:8080/...` while the API was served on `:5000`. Following that hop reaches the UI rather than the API, and because the origin changes, the HTTP client strips the `Authorization` header, so the request arrives unauthenticated and fails `403`. A tool that followed the redirect would therefore report an authorisation error for a resource the caller can in fact read.

Where a documented redirect exists, the tool SHALL disable redirect-following for that request and treat the `302` itself as the answer, reporting where the caller should go instead. `get_entityset` does this: a profile-type set yields the profile id and a `_note` naming `get_profile`, with no second request issued.

The origin pin covers scheme, host and port, so a same-host, different-port redirect **is** refused by the guard — see "Requests that leave the configured origin or base path are refused" above. Even so, the pin SHALL NOT be treated as the reason a redirect is safe to follow: any future tool that follows one SHALL re-derive the target against the configured API base rather than trusting the advertised `Location`.

#### Scenario: A profile redirect is reported rather than followed

- **WHEN** `get_entityset` is called with a profile id and Aleph answers `302` with a `Location` on its public UI origin
- **THEN** no request is issued to that `Location`
- **AND** the tool returns `type: "profile"`, the same id, and a `_note` naming `get_profile`

#### Scenario: A redirect into an unlisted path is refused mid-chain

- **WHEN** an allowlisted request receives a redirect to a path that is not allowlisted
- **THEN** the redirected request is refused before transmission
- **AND** no response from the redirect target is returned to the caller

### Requirement: An encoded path cannot present as an allowlisted one

The guard matches against the decoded request path. This SHALL remain safe only while the accepted id character set excludes `%`: decoding can introduce additional path separators, which makes a full-match against a fixed number of segments stricter, never looser.

If the accepted id character set is ever widened to include `%`, the guard SHALL be changed to match the encoded path instead. That condition is part of this requirement, not an implementation note.

#### Scenario: Encoded traversal is refused

- **WHEN** a request path contains encoded traversal or separator sequences, such as `%2F`, `%2e%2e`, `%00`, or a bare `//`, that would resolve to a mutating endpoint
- **THEN** the request is refused

#### Scenario: Encoding an allowlisted path does not change the verdict

- **WHEN** a request encodes characters within an otherwise allowlisted path, such as `/api/2/entities/e%31`
- **THEN** it is allowed, and it addresses the same endpoint the decoded form addresses

### Requirement: No caller-supplied value may introduce a query parameter name

The allowlist deliberately matches on method and path only; query strings are not part of that match. The query surface is instead closed at the point of construction: every query parameter name SHALL be either a fixed literal chosen by this server, or a caller-supplied value confined to a namespaced prefix such as `filter:`, `facet_size:` or `facet_total:`.

A caller SHALL NOT be able to introduce a bare parameter name, and SHALL NOT be able to terminate one parameter and begin another.

Stating this is the point: without it, a reader reasonably concludes the allowlist covers query strings, and it does not.

#### Scenario: A value containing parameter separators stays inside its namespace

- **WHEN** a caller supplies a filter key, facet name, or property name containing `&` or `=`, such as `refresh=true&sync=true`
- **THEN** the emitted parameter name is the namespaced form with those characters percent-encoded
- **AND** no additional query parameter appears in the request

#### Scenario: Free-text values cannot become parameter names

- **WHEN** a caller supplies such a string as a search term or a collection foreign id
- **THEN** it is emitted as a parameter value, never as a parameter name

### Requirement: Exactly one request asks Aleph to do work beyond answering

`get_collection` sends `refresh=true` on its numeric-id branch, which asks Aleph to recompute the collection's statistics. This SHALL be the only request the server issues that asks Aleph to perform work beyond answering the question asked. It creates, modifies and deletes nothing.

Any additional request of this kind SHALL require this requirement to be amended, so that the exception list cannot grow silently.

#### Scenario: The recompute request is the only one of its kind

- **WHEN** the query parameters this server emits are enumerated across every tool
- **THEN** `refresh=true` on the collection-by-numeric-id request is the only parameter that instructs Aleph to perform work

### Requirement: Transport confidentiality is out of scope for this guarantee

The read-only guarantee constrains what this server sends, not what an observer can read or forge. Configuration permits an `http://` host and disabling TLS verification. Under either, the API key can travel in clear and responses can be substituted.

This SHALL be recorded as a stated position rather than left as an oversight: the guarantee is "this server cannot write", not "this connection is trustworthy". Neither setting weakens the refusal behaviour above.

#### Scenario: A plaintext host is accepted and does not weaken refusal

- **WHEN** the server is configured with an `http://` host
- **THEN** configuration succeeds
- **AND** every refusal requirement above continues to hold unchanged
