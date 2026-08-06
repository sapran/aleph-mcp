# read-only-guard Specification

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: An Aleph redirect is not assumed to stay on the API

Aleph builds redirect `Location` headers from its configured **public UI URL**, which on a real deployment is a different host and port from the API the client is connected to. A redirect SHALL therefore NOT be assumed to land on the Aleph API, and a tool SHALL NOT depend on following one to produce its result.

This was verified against a live instance: `GET /api/2/entitysets/<id>` for a profile-type set returned `302` with `Location: http://localhost:8080/...` while the API was served on `:5000`. Following that hop reaches the UI rather than the API, and because the origin changes, the HTTP client strips the `Authorization` header, so the request arrives unauthenticated and fails `403`. A tool that followed the redirect would therefore report an authorisation error for a resource the caller can in fact read.

Where a documented redirect exists, the tool SHALL disable redirect-following for that request and treat the `302` itself as the answer, reporting where the caller should go instead. `get_entityset` does this: a profile-type set yields the profile id and a `_note` naming `get_profile`, with no second request issued.

The host pin compares hostnames and not ports, so a same-host, different-port redirect is not refused by the guard. That is acceptable only because the client strips credentials across the origin change and because no tool now follows such a redirect; it SHALL NOT be relied upon as a boundary, and any future tool that follows a redirect SHALL re-derive the target against the configured API base rather than trusting the advertised `Location`.

#### Scenario: A profile redirect is reported rather than followed

- **WHEN** `get_entityset` is called with a profile id and Aleph answers `302` with a `Location` on its public UI origin
- **THEN** no request is issued to that `Location`
- **AND** the tool returns `type: "profile"`, the same id, and a `_note` naming `get_profile`

#### Scenario: A redirect into an unlisted path is refused mid-chain

- **WHEN** an allowlisted request receives a redirect to a path that is not allowlisted
- **THEN** the redirected request is refused before transmission
- **AND** no response from the redirect target is returned to the caller
