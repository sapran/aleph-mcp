# Implementation notes

Findings recorded during other work, kept out of the change that surfaced them.

## Id validation is looser than the read-only allowlist (from the read-only guard review)

The read-only allowlist in `src/aleph_mcp/readonly.py` matches with `re.fullmatch`; the id
validators in `src/aleph_mcp/client.py` (`_check_entity_id`, `_check_collection_id`) still use
`re.match` with a `$` anchor. None of the differences below can widen the allowlist — every one
of them fails closed — but they produce confusing errors:

- `$` matches before a trailing newline, so `entity_id="e1\n"` passes validation and then dies
  inside httpx with an opaque `InvalidURL` that no tool translates (each `@mcp.tool` catches only
  `ValueError`). Fix: `re.fullmatch`, or `\Z` instead of `$`.
- The id charset allows `.`, so `entityset_id=".."` is accepted and httpx normalises the dot
  segment away at URL construction: `/api/2/entitysets/../entities` becomes `/api/2/entities`,
  which is an allowlisted read. The caller learns nothing `search_entities` does not already
  expose, but a nonsense id should fail with a clear `ValueError`.
- The guard inspects `httpx.URL.path` (percent-decoded) while the transport sends
  `raw_path` (encoded). Safe today only because the id charset excludes `%`: decoding can add
  `/` separators, which makes `fullmatch` stricter, never looser. If that charset is ever
  widened to include `%`, the hook must match `request.url.raw_path` instead.

## `GET /api/2/collections/{id}?refresh=true` is a side-effecting read

`AlephClient.get_collection` always passes `refresh=true` on the numeric-id branch, which asks
Aleph to recompute the collection's statistics. It creates, changes and deletes nothing, so it
does not contradict the read-only guarantee, but it is the only request in the package that asks
the server to do work beyond answering. Worth naming explicitly if the guarantee is ever audited
externally.
