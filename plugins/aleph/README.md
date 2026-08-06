# `aleph` plugin

Installs the [`aleph-mcp`](https://github.com/sapran/aleph-mcp) read-only MCP server, and
the method skill that tells an agent how to work an Aleph instance as an entity graph
rather than a document pile.

## What it installs

- **One MCP server**, `aleph:mcp` — 17 read tools and 3 resources (`aleph://collections`,
  `aleph://schemata`, `aleph://schema/{name}`).
- **One skill**, `aleph-entity-graph` — inventory → facet → filter → pivot → read-bounded,
  plus the Aleph limits that change the method (the 9999 window, the 200-entity expansion
  cap, the 10,000 total cap, read-only bulk-export refusal).

Under omp the plugin's server is namespaced `<plugin>:<server key>` = `aleph:mcp`, and tool
names are `mcp__<sanitized server>_<tool>`. So the model sees **`mcp__aleph_mcp_<tool>`** —
for example `mcp__aleph_mcp_search_entities`.

## Prerequisites

- [`uv`](https://github.com/astral-sh/uv) on `PATH` (it provides `uvx`). Python ≥ 3.12 is
  fetched by `uv` itself.
- An Aleph API key belonging to a role whose collection ACL is `read=true, write=false`.
  The credential — not tool-level permission — is the real boundary here; see
  [why read-only is enforced outside the agent](../../README.md#why-read-only-and-why-it-is-enforced-outside-the-agent).

## Install (omp)

```bash
omp plugin marketplace add sapran/aleph-mcp
omp plugin install aleph@aleph-mcp
```

Marketplace mutations made from the TUI or CLI do not refresh a live session: run
`/reload-plugins` to pick up the skill and the MCP server, or restart omp.

For a single repository instead of your user scope, add `--scope project`:

```bash
omp plugin install aleph@aleph-mcp --scope project
```

## Install (Claude Code)

```
/plugin marketplace add sapran/aleph-mcp
/plugin install aleph@aleph-mcp
```

The catalog lives at `.claude-plugin/marketplace.json`, which both harnesses read.

## Where the Aleph URL and key go

Two variables, both required:

| Variable | Notes |
| --- | --- |
| `ALEPHCLIENT_HOST` | Site root, e.g. `https://aleph.occrp.org`. A trailing `/api/2` or `/api` is tolerated and stripped. |
| `ALEPHCLIENT_API_KEY` | Use a READ-only role. |

Optional: `ALEPH_MCP_TIMEOUT_SECS` (default `60`), `ALEPH_MCP_MAX_RETRIES` (default `4`),
`ALEPH_MCP_VERIFY_TLS` (default `true`; set `false` for a self-signed instance).

**Never put them in `plugins/aleph/.mcp.json`.** That file is committed and shared, which is
why it carries no `env` block at all.

- **omp, all projects (recommended) — `~/.omp/.env`:**

  ```dotenv
  ALEPHCLIENT_HOST=https://aleph.example.org
  ALEPHCLIENT_API_KEY=<key>
  ```

  omp loads this into its own process environment at startup, and the MCP stdio child
  inherits that environment, so no per-client `env` block is needed. Then
  `chmod 600 ~/.omp/.env`.

- **omp, one project only — `<project>/.env`:** the same two lines. It wins over
  `~/.omp/.env`. Full precedence, highest first: inherited process environment →
  `<cwd>/.env` → `~/.omp/agent/.env` → `~/.omp/.env` → `~/.env`. A variable already present
  in the process environment is never overwritten by any `.env` file.

- **Any harness, including Claude Code and opencode — export in your shell rc**
  (`~/.zshrc`), because only omp autoloads `.env`:

  ```bash
  export ALEPHCLIENT_HOST=https://aleph.example.org
  export ALEPHCLIENT_API_KEY=<key>
  ```

  Alternatively add an `env` block to that client's own MCP entry — but then the literal
  value sits in that client's config file.

- **Per-instance override without touching the plugin** — also the answer to "I have two
  Aleph instances". Declare a same-purpose server in `~/.omp/agent/mcp.json` with an
  explicit `env` block, and disable the plugin's one:

  ```json
  {
    "mcpServers": {
      "aleph-eu": {
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", "git+https://github.com/sapran/aleph-mcp.git", "aleph-mcp"],
        "env": {
          "ALEPHCLIENT_HOST": "https://aleph.eu.example.org",
          "ALEPHCLIENT_API_KEY": "<key>"
        }
      }
    },
    "disabledServers": ["aleph:mcp"]
  }
  ```

  A config `env` block is an overlay on the inherited environment, not a replacement.

## Verify

```bash
omp plugin list          # expect: aleph@aleph-mcp, enabled
```

In a session, `/mcp list` shows `aleph:mcp` connected and `/mcp test aleph:mcp` passes.

**If no `mcp__aleph_mcp_*` tool appears**, check that omp's Claude-marketplace discovery
provider is not switched off:

```bash
omp config list | grep disabledProviders
```

A `claude-plugins` entry in that list disables every capability this plugin ships — MCP
server, skill and all — because plugin discovery is what loads them. Remove `claude-plugins`
from `disabledProviders` in `~/.omp/agent/config.yml`, or override it for a single run with
`--config <overlay.yml>`. The other entries (`claude`, `opencode`, `cursor`, `codex`) are
unrelated and can stay.

If the credentials are missing, the server exits `2` and these lines appear in the MCP logs:

```
aleph-mcp: configuration error: …
aleph-mcp: set ALEPHCLIENT_HOST and ALEPHCLIENT_API_KEY (use a READ-only Aleph role).
```

That is the intended failure: no `env` block means an unset variable stays unset, instead of
a passthrough map handing the server the literal string `ALEPHCLIENT_API_KEY` and turning a
clean exit into a runtime 403.

## Pinning and updates

```bash
omp plugin marketplace update aleph-mcp
omp plugin upgrade aleph@aleph-mcp
```

That refreshes the plugin files. The **server build** is resolved and cached separately by
`uvx`, so to pick up new server code add `--refresh` to the args in `.mcp.json` or run:

```bash
uv cache clean aleph-mcp
```

To pin a version, change the `--from` spec to
`git+https://github.com/sapran/aleph-mcp.git@<tag>`. The shipped spec is deliberately
unpinned because the repository carries no release tag yet.

## Local development

To run the server from a checkout instead of git, put this in `~/.omp/agent/mcp.json` and
disable the plugin's server:

```json
{
  "mcpServers": {
    "aleph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/aleph-mcp", "aleph-mcp"]
    }
  },
  "disabledServers": ["aleph:mcp"]
}
```

This form is not plugin-namespaced, so it yields the shorter tool names
`mcp__aleph_<tool>`.

## Listing this plugin from another marketplace

For another catalog — say `sapran/acordia-agents` — to offer this plugin without vendoring
a copy, its entry is a `git-subdir` source:

```json
{
  "name": "aleph",
  "description": "Read-only MCP server over the OCCRP Aleph HTTP API.",
  "category": "security",
  "source": {
    "source": "git-subdir",
    "url": "https://github.com/sapran/aleph-mcp.git",
    "path": "plugins/aleph",
    "ref": "main"
  }
}
```

Documentation only — no change is made to any other catalog by this repository.
