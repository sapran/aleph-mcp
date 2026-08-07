# Implementation notes

Findings recorded during other work, kept out of the change that surfaced them. An entry leaves
this file when it becomes a spec requirement or is fixed — not when someone remembers to tidy up.

- **The shipped plugin `.mcp.json` runs a shell at every server start.** Both `env` values
  are `!`-prefixed commands: the host is `$ALEPHCLIENT_HOST`, and the key is read from the
  macOS login Keychain under a service name that includes the host. That behaviour is
  documented in `plugins/aleph/README.md` rather than only implied, because installing the
  plugin makes a Keychain read happen per session. A miss deliberately prints the marker
  `aleph-mcp:keychain-miss` instead of an empty string: the harness *omits* an `env` entry
  whose command prints only whitespace, and an omitted entry lets the server inherit an
  ambient `ALEPHCLIENT_API_KEY`. Non-macOS users are directed to declare their own server
  entry instead.

Retired since the last prune:

- The version being written in three places with nothing checking they agree — which shipped
  0.1.4 to every marketplace user as 0.1.2, because the *catalog* version is what drives
  change detection in `omp plugin upgrade`. **Fixed** by `tests/test_packaging.py`, which
  asserts the three declared versions equal `aleph_mcp.__version__`.
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
