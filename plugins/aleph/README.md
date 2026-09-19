# `aleph` plugin for Claude Code and omp

Installs the [`aleph-mcp`](https://github.com/sapran/aleph-mcp) read-only MCP server and
the method skill that tells an agent how to work an Aleph instance as an entity graph
rather than a document pile.

This is a Claude marketplace plugin. Claude Code loads it directly; omp loads it through
the `claude-plugins` discovery provider.

## What it installs

- **One MCP server**, keyed `mcp` inside the `aleph` plugin, with 17 read tools and 3
  resources (`aleph://collections`, `aleph://schemata`, `aleph://schema/{name}`).
- **One skill**, `aleph-mcp-entity-graph`: inventory → facet → filter → pivot →
  read-bounded, plus the Aleph limits that change the method.

## Prerequisites

- [`uv`](https://github.com/astral-sh/uv) on `PATH` (it provides `uvx`). Python ≥ 3.12 is
  fetched by `uv` itself.
- An Aleph API key belonging to a role whose collection ACL is `read=true, write=false`.
  The credential, not tool-level permission, is the real boundary here. See
  [why read-only is enforced outside the agent](../../README.md#why-read-only-and-why-it-is-enforced-outside-the-agent).

## Install

### omp

Check the effective provider list:

```bash
omp config get disabledProviders
```

If it contains `claude-plugins`, remove only that entry from the list that supplied it.
Check the current project's `.omp/config.yml` first. Then check the active agent directory
printed by `omp config path`: edit its existing `config.yaml` when present, otherwise
`config.yml`. Preserve every other entry, and remember which file you changed so
uninstall can restore it. Enabling this provider loads all installed Claude marketplace
plugins, not only Aleph.

```bash
omp plugin marketplace add sapran/aleph-mcp
omp plugin install aleph@aleph-mcp --scope user
```

Use `--scope project` for one project. For a named profile, prefix every command in this
section, including the configuration checks, with `omp --profile <name>`.

### Claude Code

```text
/plugin marketplace add sapran/aleph-mcp
/plugin install aleph@aleph-mcp
```

Restart the client after installation so both the skill and MCP server are loaded. The
catalog is `.claude-plugin/marketplace.json`.

## Where the Aleph URL and key go

Two variables, both required:

| Variable | Notes |
| --- | --- |
| `ALEPHCLIENT_HOST` | Site root, e.g. `https://aleph.occrp.org`. A trailing `/api/2` or `/api` is tolerated and stripped. |
| `ALEPHCLIENT_API_KEY` | Use a READ-only role. |

Optional: `ALEPH_MCP_TIMEOUT_SECS` (default `60`), `ALEPH_MCP_MAX_RETRIES` (default `4`),
`ALEPH_MCP_VERIFY_TLS` (default `true`; set `false` for a self-signed instance).

**Never put the key itself in `plugins/aleph/.mcp.json`.** That committed file carries
no credentials and does not override the process environment. At startup, the runtime
selects the first **complete** host-and-key pair in this order:

1. The inherited process environment: `ALEPHCLIENT_HOST` plus
   `ALEPHCLIENT_API_KEY` (the `ALEPH_HOST` / `ALEPH_API_KEY` and `ALEPH_MCP_HOST` /
   `ALEPH_MCP_API_KEY` aliases also work).
2. The same pair in `<current project>/.env`.
3. The macOS login Keychain entries described below.

An incomplete source is ignored rather than combined with a lower-priority source. A
host from a project `.env` therefore cannot be paired with a Keychain API key. The
runtime parses `.env` as configuration data; it never shell-sources it. In omp, every
stdio MCP child inherits ambient variables, so prefer the server-specific Keychain
entries when unrelated marketplace plugins are installed.



### Storing the host and key

For the omp plugin on macOS, prefer distinct Keychain services so only the Aleph launcher
reads the secret. Ensure neither the inherited environment nor the current project's
`.env` already provides a complete pair, because those sources take precedence:

```bash
security add-generic-password -s "aleph-mcp-host" \
  -a "$USER" -w "https://aleph.example.org" -U
security add-generic-password -s "aleph-mcp-api-key" \
  -a "$USER" -w '<api-key>' -U
```

The distinct host service deliberately avoids the old `aleph-mcp` service, which prior
releases used for an API key. A stale legacy key therefore cannot become the configured
host. The launcher never prints a Keychain value or lookup diagnostic.

## Verify

In omp, run `/mcp list`; in Claude Code, open MCP status. Confirm the plugin server is
connected and `aleph-mcp-entity-graph` is available, then call `list_collections`. A
non-zero collection total is the credential proof; a connected process or listed schema
is not.

If the credentials are missing, the server exits `2` and these lines appear in the MCP
logs:

```
aleph-mcp: configuration error: …
aleph-mcp: set ALEPHCLIENT_HOST and ALEPHCLIENT_API_KEY (use a READ-only Aleph role).
```

That is the intended failure when none of the three sources provides a complete
credential pair. The runtime checks the inherited environment first, then
`<current project>/.env`, then the two Keychain services. It still rejects the legacy
refusal marker emitted by an older installed plugin manifest.

## Pinning and updates

For omp, omitting `--scope` upgrades every installed scope in the selected profile:

```bash
omp plugin marketplace update aleph-mcp
omp plugin upgrade aleph@aleph-mcp
```

For a named profile, prefix both commands with `omp --profile <name>`.

For Claude Code:

```text
/plugin marketplace update aleph-mcp
/plugin update aleph@aleph-mcp
```

These commands refresh the plugin files. The **server build** is resolved and cached
separately by `uvx`; run `uv cache clean aleph-mcp` if the updated commit does not resolve.

The shipped `--from` spec is pinned to a full commit SHA. That is deliberate: this server
is handed your Aleph API key, and an unpinned `git+` spec would run whatever the default
branch happened to contain. Each release bumps the SHA, so updating the plugin moves the
server forward.

Restart the client after an update:

```bash
omp plugin list --json
```

Use the same `--profile`, if any. Select each installed scope's `installPath`, then compare
that directory's `.mcp.json` SHA with the target release's `plugins/aleph/.mcp.json`. This
follows omp's actual data root even when XDG relocates it; the refreshed catalog and
displayed version alone are not payload proof. Finally check `/mcp list` and make one real
Aleph call.

## Remove from omp

First run `omp plugin list`. Uninstall every scope shown, then remove the marketplace:

```bash
# Run each uninstall whose scope is listed
omp plugin uninstall aleph@aleph-mcp --scope user
omp plugin uninstall aleph@aleph-mcp --scope project
omp plugin marketplace remove aleph-mcp
```

For a named profile, prefix every command with `omp --profile <name>`. If Aleph was the
reason you enabled `claude-plugins`, add it back to the same `disabledProviders` list
after confirming no remaining plugin needs that provider. Restart omp and confirm
`aleph:mcp` is absent from `/mcp list`.


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
