## Why

The documented omp marketplace install can register Aleph while exposing none of its capabilities when `claude-plugins` is disabled. Enabling that shared provider also imports unrelated Claude Code plugins, so omp needs a native package that installs the Aleph MCP server and method skill without crossing that boundary.

## What Changes

- Publish a dedicated `plugins/aleph-omp/` bundle as the native omp package `@sapran/aleph-mcp-plugin`.
- Give the native bundle its own `aleph:mcp` server definition and a byte-identical copy of the `aleph-mcp-entity-graph` skill; retain `plugins/aleph/` for Claude Code's marketplace prefixing rules.
- Replace the omp marketplace instructions with a version-pinned native `omp plugin install` command; retain the marketplace path for Claude Code.
- Add packaging guards and an isolated-profile acceptance journey that prove the documented install exposes `aleph:mcp` with 17 tools and the skill while `claude-plugins` remains disabled.
- Extend release version checks and publishing instructions so the Python release, Claude plugin, and native omp package cannot drift.

## Capabilities

### New Capabilities

- `plugin-distribution`: Native omp and Claude Code distribution contracts, including package contents, discovery isolation, version alignment, and clean-install verification.

### Modified Capabilities

None.

## Impact

Affected files include the new `plugins/aleph-omp/` package, packaging tests, install documentation, and release automation or instructions. The MCP API, Aleph credential resolution, read-only allowlist, and tool behavior do not change. Publishing adds an npm registry artifact under the `@sapran` scope.
