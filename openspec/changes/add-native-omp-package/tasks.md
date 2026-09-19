## 1. Package Contract

- [x] 1.1 Replace the discarded single-root tests with failing guards for a dedicated `plugins/aleph-omp/` manifest, native `aleph:mcp` key, exact artifact inventory, byte-identical skill trees, and equal MCP server bodies; verify the focused tests fail because the native bundle is absent.
- [x] 1.2 Add `plugins/aleph-omp/` as public package `@sapran/aleph-mcp-plugin`, with its own keyed MCP definition, plugin README, and copied skill tree; verify the focused packaging tests pass.
- [x] 1.3 Run `npm pack --dry-run --json --ignore-scripts` in `plugins/aleph-omp/` and verify the artifact contains only the license, package manifest, native MCP definition, README, and complete skill tree.

## 2. Native Runtime Journey

- [x] 2.1 Link the package directory into a uniquely named disposable omp profile whose `disabledProviders` includes `claude-plugins`; verify a fresh session reports the Aleph server with 17 tools, resolves `skill://aleph-mcp-entity-graph`, preserves the documented tool namespace, and does not expose Context7.
- [ ] 2.2 Uninstall the linked package from the disposable profile; verify a fresh session exposes neither the Aleph server nor the skill, then remove only the verified disposable profile directory.

## 3. Documentation And Release Metadata

- [x] 3.1 Replace omp marketplace install, update, verify, and remove commands in `README.md` with the version-pinned native package route; retain `plugins/aleph/README.md` for Claude Code and add the native operator README under `plugins/aleph-omp/`.
- [x] 3.2 Update release/version documentation and guards to cover the fourth metadata version in `plugins/aleph-omp/package.json` and both version-pinned native install commands; mutation-prove that the packaging test detects one-file version drift.
- [x] 3.3 Run the English punctuation gate over changed prose and fix every finding.

## 4. Repository Verification

- [x] 4.1 Run the focused packaging tests, full mocked test suite, Ruff, and mypy; record clean command output.
- [ ] 4.2 Validate the OpenSpec change strictly and verify the implementation against the proposal, design, delta spec, and task list.

## 5. Published Artifact Verification

- [ ] 5.1 Publish the approved package version, then install that exact registry version into a clean disposable omp profile with `claude-plugins` disabled.
- [ ] 5.2 Repeat the server, 17-tool, skill, namespace, unrelated-plugin absence, uninstall, and cleanup journey against the registry artifact before declaring the release complete.
