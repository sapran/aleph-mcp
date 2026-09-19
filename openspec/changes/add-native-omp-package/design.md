## Context

See `proposal.md` for motivation. Omp has two plugin paths with different discovery and naming rules. Marketplace installs are served through `claude-plugins`, which prefixes server key `mcp` with marketplace plugin name `aleph`. Native npm or linked plugins are served through `omp-plugins` and expose the raw server key. A real TUI probe showed that reusing `plugins/aleph/` natively produces `mcp` and `mcp__mcp_<tool>`, so the two distributions cannot share one `.mcp.json`.

## Goals / Non-Goals

**Goals:**

- Make one version-pinned `omp plugin install` command deliver the MCP server and skill through `omp-plugins`.
- Preserve the existing Aleph MCP and tool naming contract.
- Keep Claude Code on the existing marketplace distribution.
- Prove package contents before publication and prove runtime discovery from the published artifact after publication.

**Non-Goals:**

- Change MCP tools, resources, credentials, or read-only enforcement.
- Enable `claude-plugins` or alter any operator's unrelated plugin registry.
- Add a postinstall script, generated user configuration, native symlink farm, or fallback MCP entry.
- Publish the Python server to PyPI.

## Decisions

### Publish `plugins/aleph-omp/` as `@sapran/aleph-mcp-plugin`

A dedicated native bundle contains `package.json`, `.mcp.json` keyed as `aleph:mcp`, a plugin README, and the method skill. Its explicit `files` allowlist keeps the npm artifact bounded. The native package contains no install lifecycle scripts.

A scoped package avoids claiming a generic global name and makes publisher ownership explicit. The README pins the installed version.

### Keep the Claude marketplace as a separate distribution

`.claude-plugin/marketplace.json` continues to point at `plugins/aleph/` for Claude Code, where server key `mcp` is correct because the marketplace loader supplies the `aleph:` prefix. Omp documentation stops recommending this path.

### Guard duplicated runtime contracts

The two `.mcp.json` files intentionally differ only in server key. Packaging tests compare their server bodies byte-for-byte after extracting the keyed object, so command, arguments, and immutable SHA cannot drift. The two skill trees are byte-identical and tested recursively. `npm pack --dry-run --json` in `plugins/aleph-omp/` must also match an exact bounded inventory.

### Verify runtime in two stages

Before publication, a disposable omp profile links the package directory and keeps `claude-plugins` disabled. The probe checks server discovery, 17 tools, skill resolution, and absence of a known Claude-registry MCP such as Context7. After publication, a second disposable profile installs the exact npm version and repeats the same checks. The release is incomplete until the registry-backed journey passes.

### Preserve naming through an acceptance probe

The native bundle's `.mcp.json` uses the explicit `aleph:mcp` key. A real interactive TUI probe, not print-mode model prose, must show `aleph:mcp` and `mcp__aleph_mcp_<tool>`. Any other namespace blocks release.

## Risks / Trade-offs

- Publishing requires npm access to the `@sapran` scope. Missing access blocks release rather than falling back to a manual install.
- The release adds a fourth synchronized metadata version and two version-pinned native install commands. A guard test and release checklist make drift fail before publication.
- Claude marketplace and npm consumers update through different commands. Separate README sections make that split explicit.
- Maintaining two small distribution trees adds duplication. Recursive byte-identity guards make drift fail rather than relying on memory.
- Omp profile cleanup is destructive. Verification uses a uniquely named disposable profile and removes it only after confirming its exact path.
