# Implementation notes

Findings recorded during other work, kept out of the change that surfaced them. An entry leaves
this file when it becomes a spec requirement or is fixed — not when someone remembers to tidy up.

Retired since the last prune:

- The `$` anchor letting `entity_id="e1\n"` through, and `entityset_id=".."` normalising away to
  a different endpoint. **Fixed** by `fix-id-validation-anchors`; the validators now use
  `re.fullmatch`, as the allowlist always has.
- The guard matching a decoded path while the transport sends the encoded one. **Specified** by
  `baseline-read-only-guard` as a requirement that carries its own invalidating condition, with
  `test_id_charset_excludes_percent` as the tripwire: if `%` is ever added to the accepted id
  charset, that test fails and the guard must move to `raw_path`.
- `GET /api/2/collections/{id}?refresh=true` asking Aleph to recompute statistics. **Specified**
  by `baseline-read-only-guard` as the single named exception to "asks the server only to
  answer", with `test_refresh_is_emitted_by_exactly_one_request` as the tripwire so the exception
  list cannot grow quietly.
- The acordia ↔ aleph-mcp seam existing only as prose. **Declared** by
  `declare-acordia-spec-reference` as a `references:` entry in `openspec/config.yaml`, so
  `openspec doctor` reports it instead of `(none declared)`. Records-only by design — a reference
  indexes the referenced root's specs once its store is registered locally and runs no cross-root
  drift check (`dist/core/references.js`: "root resolution is never affected") — and the store is
  intentionally left unregistered so nothing is written into acordia. The tool-name expectation is
  therefore visible, not enforced; asserting it would invert the dependency.
