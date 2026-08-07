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

**Never put the key itself in `plugins/aleph/.mcp.json`.** That file is committed and
shared. Its `env` block contains no secret: it forwards `$ALEPHCLIENT_HOST` from your
environment, and looks the key up in the macOS login Keychain under a service name
**keyed on that host**. The binding is the point — see "Why the Keychain entry is
host-scoped" below.

- **The plugin (macOS) — host in the environment, key in the Keychain.** Put the URL
  wherever omp reads it, e.g. `~/.omp/.env` (then `chmod 600 ~/.omp/.env`):

  ```dotenv
  ALEPHCLIENT_HOST=https://aleph.example.org
  ```

  and store the key against that exact host, as shown below. An `ALEPHCLIENT_API_KEY` in
  a `.env` file or your shell rc is **not** used by the plugin: its `env` block always
  supplies the key, and supplies a refusal marker when the Keychain holds no entry for
  the host in play, so the server stops instead of starting against the wrong instance.
  That is deliberate — see "Why the Keychain entry is host-scoped".

  omp's `.env` precedence, highest first, is: inherited process environment →
  `<cwd>/.env` → `~/.omp/agent/.env` → `~/.omp/.env` → `~/.env`. A variable already
  present in the process environment is never overwritten by any `.env` file.

- **Not on macOS, or you keep the key in a file** — do not use the plugin's server entry.
  Disable it and declare your own with an explicit `env` block, as under "Per-instance
  override without touching the plugin" below. Both variables are then yours to place,
  together, from a single source you control.

- **Per-instance override without touching the plugin** — also the answer to "I have two
  Aleph instances". Declare a same-purpose server in `~/.omp/agent/mcp.json` with an
  explicit `env` block, and disable the plugin's one:

  ```json
  {
    "mcpServers": {
      "aleph-eu": {
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", "git+https://github.com/sapran/aleph-mcp.git@<commit-sha>", "aleph-mcp"],
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

### Storing the key

```bash
security add-generic-password -s "aleph-mcp:https://aleph.example.org" \
  -a "$USER" -w '<api-key>' -U
```

The service name is `aleph-mcp:` followed by the host **exactly as `ALEPHCLIENT_HOST`
is set** — same scheme, no trailing slash. A harness that is not the plugin reads it
back the same way:

```bash
export ALEPHCLIENT_API_KEY="$(security find-generic-password \
  -s "aleph-mcp:$ALEPHCLIENT_HOST" -a "$USER" -w 2>/dev/null)"
```

**Why the Keychain entry is host-scoped.** `ALEPHCLIENT_HOST` comes from the ambient
environment, and `<cwd>/.env` outranks `~/.omp/.env` in the precedence above — so a
`.env` arriving inside a cloned repository or an extracted archive can redirect the
client to an origin the attacker chose. Nothing else would notice: the read-only guard
pins whatever host it was configured with, so it would approve every request to the
substituted origin. Keying the entry on the host means the substituted host finds no
credential; the plugin then passes an explicit refusal marker rather than an empty
value, because an empty one would let the child inherit your real key from the ambient
environment instead. The server stops at startup and says which host it was pointed at.

Upgrading from 0.1.4 or earlier: re-store the key under the new name, then
`security delete-generic-password -s aleph-mcp -a "$USER"`.

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

If the credentials are missing, the server exits `2` and these lines appear in the MCP
logs:

```
aleph-mcp: configuration error: …
aleph-mcp: set ALEPHCLIENT_HOST and ALEPHCLIENT_API_KEY (use a READ-only Aleph role).
```

That is the intended failure. The `env` block resolves each value by running a shell
command — `$ALEPHCLIENT_HOST` for the URL, a login-Keychain read for the key — at every
server start, and a lookup that finds nothing yields a refusal marker rather than a
plausible-looking empty string. So an unset or mismatched credential produces a clean
exit naming the cause, instead of a passthrough map handing the server a literal
`ALEPHCLIENT_API_KEY` and turning it into a runtime 403.

If the error names a host you did not expect, a `.env` in the working directory has
redefined `ALEPHCLIENT_HOST`; that is the case the host-scoped Keychain entry exists to
catch.

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

The shipped `--from` spec is pinned to a full commit SHA. That is deliberate: this server
is handed your Aleph API key, and an unpinned `git+` spec would resolve, build and run
whatever the default branch happened to be at launch. Each release bumps the SHA, so
updating the plugin is what moves the server forward — the pin is not a version you are
expected to edit by hand.

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
    "ref": "<commit-sha>"
  }
}
```

Pin `ref` to a release commit rather than `main`. It decides which copy of
`plugins/aleph/.mcp.json` that catalog serves — and therefore which server commit the
plugin installs and hands the Aleph key to. A mutable `ref` puts that choice in the hands
of whoever can push to the default branch.

Documentation only — no change is made to any other catalog by this repository.
