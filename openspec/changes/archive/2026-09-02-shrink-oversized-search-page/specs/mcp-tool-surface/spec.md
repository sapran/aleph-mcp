## ADDED Requirements

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
