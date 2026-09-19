# Aleph MCP plugin for omp

This native omp package installs the read-only Aleph MCP server and the
`aleph-mcp-entity-graph` method skill. It does not use or enable Claude Code plugin
discovery.

## Prerequisites

- `bun` on `PATH`, as required by omp's native plugin manager.
- `uv` on `PATH` to run the pinned MCP server through `uvx`.
- `ALEPHCLIENT_HOST` and `ALEPHCLIENT_API_KEY` for a read-only Aleph role.

## Install

```bash
omp plugin install @sapran/aleph-mcp-plugin@0.5.1
```

Restart omp after installation. The package inherits `ALEPHCLIENT_HOST` and
`ALEPHCLIENT_API_KEY` from omp's environment; see the
[project configuration guide](https://github.com/sapran/aleph-mcp#configure).

## Verify

In the restarted session, `/mcp list` must show `aleph:mcp` connected with 17 tools.
The tools use the `mcp__aleph_mcp_<tool>` form, and
`skill://aleph-mcp-entity-graph` must resolve. Then call `list_collections`; a non-zero
`total` is the credential proof. Aleph returns HTTP 200 with zero collections for an
invalid or expired key, so process and tool discovery alone are not enough.

## Update

Install the new version explicitly:

```bash
omp plugin install @sapran/aleph-mcp-plugin@<version>
```

For a named profile, use
`omp --profile <name> plugin install @sapran/aleph-mcp-plugin@<version>`.

Restart omp and repeat the verification above.

## Remove

```bash
# Default profile
omp plugin uninstall @sapran/aleph-mcp-plugin

# Named profile
omp --profile <name> plugin uninstall @sapran/aleph-mcp-plugin
```

Restart omp. The server and skill must both be absent; no manual MCP or skill cleanup
is required.
