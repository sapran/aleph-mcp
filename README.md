# aleph-mcp

A **read-only** [MCP](https://modelcontextprotocol.io) server over the
[Aleph](https://github.com/alephdata/aleph) HTTP API, so an LLM agent can search,
pivot and read an investigative dataset without being able to change it.

## Why read-only, and why it is enforced outside the agent

Aleph's write surface is destructive: `DELETE /api/2/collections/<id>` removes an entire
investigation, `POST .../mappings/<id>/flush` drops every entity a mapping produced, and
`_bulk` with `mutable=true` overwrites entities in place. None of that is exposed here.

More importantly, **tool-level permission is not a reliable boundary.** opencode can deny
an MCP tool per agent, but omp cannot: its `xd://` transport tools are always present when
`tools.xdev` is on, regardless of an agent's allowlist. So the real boundary must be the
credential:

> **Use an Aleph role whose collection ACL is `read=true, write=false`.**
> Then destructive endpoints are refused server-side, whatever the agent calls.

Known cost of that choice: `GET /api/2/collections/<id>/_stream` requires **WRITE**
(`aleph/views/stream_api.py`), so a read-only key cannot bulk-export. This server is built
around that constraint — it is facet-first, so the agent narrows a result set instead of
trying to page through it. For genuine bulk export use a write-scoped tool run by a
human — deliberately not this server.

## Install

Requires Python ≥ 3.12 and [`uv`](https://github.com/astral-sh/uv). `aleph-mcp` is not on
PyPI, so every path below uses a `git+` spec — a bare `uvx aleph-mcp` resolves nothing.

Pin a commit on every path. An unpinned `git+` spec builds and runs whatever the branch
head happens to be, in a process you have just handed your Aleph key. Latest release:
**v0.5.2** = `e45e84dad9505e0c53278fa7a99785a2a43cf291`.

### Path A: omp marketplace plugin

The plugin installs both the MCP server and the `aleph-mcp-entity-graph` method skill.
It is served through omp's `claude-plugins` discovery provider.

First check the effective provider list:

```bash
omp config get disabledProviders
```

If it contains `claude-plugins`, remove only that entry from the list that supplied it.
Check the current project's `.omp/config.yml` first. Then check the active agent directory
printed by `omp config path`: edit its existing `config.yaml` when present, otherwise
`config.yml`. For a named profile, run the checks with `omp --profile <name>`. Preserve
every other entry, and remember which file you changed so uninstall can restore it. This
provider loads all installed Claude marketplace plugins, not only Aleph.

Then install Aleph:

```bash
omp plugin marketplace add sapran/aleph-mcp
omp plugin install aleph@aleph-mcp --scope user
```

For a named profile, prefix both install commands with `omp --profile <name>`.

Configure the credentials as described under [Configure](#configure), then restart omp.
Run `/mcp list`: the server must appear as `aleph:mcp`, with tools named
`mcp__aleph_mcp_<tool>`. Resolve `skill://aleph-mcp-entity-graph`, then make one real
`list_collections` call. A non-zero `total` is the credential proof; a connected process
or schema listing is not.

### Path B: Claude Code marketplace plugin

```text
/plugin marketplace add sapran/aleph-mcp
/plugin install aleph@aleph-mcp
```

Restart Claude Code after installation, configure the same two credentials, and verify
the MCP server plus the `aleph-mcp-entity-graph` skill. Complete plugin details:
[`plugins/aleph/README.md`](plugins/aleph/README.md).

### Path C: any stdio MCP client, by hand

Project scope in omp is `.omp/mcp.json`; user scope is `~/.omp/agent/mcp.json`. Other
clients use their own file.

```json
{
  "mcpServers": {
    "aleph": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/sapran/aleph-mcp.git@e45e84dad9505e0c53278fa7a99785a2a43cf291", "aleph-mcp"]
    }
  }
}
```

No `env` block — credentials come from the environment the client itself runs in. Under
omp this form is not plugin-namespaced, so its tools are `mcp__aleph_<tool>`.

**Prefer no `env` block at all.** The server reads the credential pair itself — the
environment, then `.env`, then the Keychain — so there is nothing for the client to pass.

If you do add one under omp, know the fallback rule: omp substitutes the value of an
environment variable when you name the variable as its own value, **but if that variable
is unset it passes the name through as a literal string**
([`mcp-config.md`](https://github.com/can1357/oh-my-pi), "Pre-connect env/header
resolution"). So this —

```json
"env": { "ALEPHCLIENT_API_KEY": "ALEPHCLIENT_API_KEY" }
```

— sends the 19-character text `ALEPHCLIENT_API_KEY` as your key whenever the variable is
not exported, and Aleph answers `200` with zero collections. Worse, it counts as a
complete environment pair, so it *shadows* a key you correctly stored in the Keychain: the
server never reaches that tier. If you want the Keychain, pass nothing and let the server
read it.

To read a secret explicitly, use omp's command form instead — a value starting with `!` is
run as a shell command, and the entry is **omitted** if it fails, rather than degrading to
a literal:

```json
"env": { "ALEPHCLIENT_API_KEY": "!security find-generic-password -s aleph-mcp-api-key -a \"$USER\" -w" }
```

Both forms are omp-specific. Other clients want a literal value, or have their own syntax
— and a literal here means the key itself sits in that config file.

### Path D: from a checkout (developing this server)

Runs your working tree, so local edits take effect on the next server start:

```bash
git clone https://github.com/sapran/aleph-mcp.git
cd aleph-mcp
uv sync --all-extras
```

```json
{
  "mcpServers": {
    "aleph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/aleph-mcp", "aleph-mcp"]
    }
  }
}
```

Use an absolute `--directory` path: the client's working directory is not yours.
`--directory` rather than `--project`, because it also makes the checkout the server's
working directory, which is where it looks for `.env`.

### opencode

`~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "aleph": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/sapran/aleph-mcp.git@e45e84dad9505e0c53278fa7a99785a2a43cf291", "aleph-mcp"],
      "enabled": true,
      "environment": {
        "ALEPHCLIENT_HOST": "https://aleph.example.org",
        "ALEPHCLIENT_API_KEY": "{env:ALEPHCLIENT_API_KEY}"
      }
    }
  }
}
```

`{env:…}` is opencode's own substitution syntax, not omp's. Tools then appear to the model
as `aleph_search_entities`, `aleph_expand_entity`, and so on
(`sanitize(server) + "_" + sanitize(tool)`).

## Configure

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `ALEPHCLIENT_HOST` | yes | — | Site root, e.g. `https://aleph.occrp.org`. A `/api/2` suffix is tolerated and stripped. |
| `ALEPHCLIENT_API_KEY` | yes | — | Aleph API key. Use a READ-only role. |
| `ALEPH_MCP_TIMEOUT_SECS` | no | `60` | Per-request HTTP timeout, and the total budget one call may spend retrying. Connecting is capped separately at 10s. |
| `ALEPH_MCP_MAX_RETRIES` | no | `4` | Attempts per request on 429/5xx (honouring `Retry-After`) and on a connection failure. The backoff between them is drawn from `ALEPH_MCP_TIMEOUT_SECS`. |
| `ALEPH_MCP_VERIFY_TLS` | no | `true` | Set `false` for a self-signed instance. |

`ALEPHCLIENT_HOST` / `ALEPHCLIENT_API_KEY` are deliberately the same names upstream
[`alephclient`](https://github.com/alephdata/alephclient) reads, so one exported key
serves both it and this server.

Missing required variables cause exit code 2 with a message on stderr, visible in the MCP
client's logs.

### Where to put them

The server selects the first complete host-and-key pair from the inherited environment,
the current project's `.env`, or its two macOS Keychain services. It never combines
values from different sources.

- **omp plugin on macOS:** prefer the server-specific Keychain entries shown in
  [`plugins/aleph/README.md`](plugins/aleph/README.md#storing-the-host-and-key). Only
  Aleph reads those entries. Do not put the key in omp's ambient `.env`: every stdio MCP
  child inherits that environment, including unrelated marketplace plugins.
- **omp plugin without Keychain:** a project `.env` containing both variables works, but
  every stdio MCP child in that session inherits them. Use a profile containing only
  plugins you trust with the Aleph key, and run `chmod 600 <project>/.env`.
- **Other harnesses:** Claude Code, opencode, and any other stdio client need the pair
  exported from the shell that launches them or set through that client's secret-aware
  MCP configuration. A literal `env` block stores the key in the config file.

The two Keychain services are `aleph-mcp-host` and `aleph-mcp-api-key`. Both must exist.
An incomplete source is ignored. Never commit the key: `.gitignore` already lists `.env`.


### Check it actually works

A server that starts, lists 17 tools and answers without error still proves nothing: Aleph
accepts an invalid key and replies `200` with an empty result set. Discriminate:

```bash
# Use the SITE ROOT here. ALEPHCLIENT_HOST may carry an /api/2 suffix — the server
# strips it, curl does not, and the doubled path 404s with a null total.
ALEPH_ROOT="${ALEPHCLIENT_HOST%/api/2}"; ALEPH_ROOT="${ALEPH_ROOT%/api}"

curl -s -o /dev/null -w '%{http_code}\n' "$ALEPH_ROOT/api/2/collections?limit=1"
curl -s -H "Authorization: ApiKey $ALEPHCLIENT_API_KEY" \
  "$ALEPH_ROOT/api/2/collections?limit=1" | jq .total
```

If the authenticated `total` is `0` and you expect collections, the key is not being
honoured — it is wrong, expired, or the client never received it. Do not read an empty
`list_collections` as "this instance is empty".

## Update

```bash
# omp: upgrades every installed scope in the selected profile
omp plugin marketplace update aleph-mcp
omp plugin upgrade aleph@aleph-mcp

# Claude Code
/plugin marketplace update aleph-mcp
/plugin update aleph@aleph-mcp

# Standalone tool install
uv tool upgrade aleph-mcp                # only follows the spec it was installed with
uv tool install --force git+https://github.com/sapran/aleph-mcp.git@<new-commit-sha>

# Checkout
git pull && uv sync --all-extras
```

For a named omp profile, prefix both omp commands with `omp --profile <name>`.

A hand-written `mcp.json` pins a SHA, so it never updates by itself: edit the SHA. `uvx`
caches the built environment per spec, so a changed SHA is a new environment and an
unchanged one is never rebuilt.

Restart the client afterwards. A running server keeps the old code:

```bash
omp plugin list --json
```

Use the same `--profile`, if any. Select each installed scope's `installPath`, then compare
that directory's `.mcp.json` SHA with the target release's `plugins/aleph/.mcp.json`. This
follows omp's actual data root even when XDG relocates it; the refreshed catalog and
displayed version alone are not payload proof. Finally check `/mcp list` and make one real
Aleph call.

## Remove

```bash
# omp: inspect the installed scopes first
omp plugin list

# Run each uninstall whose scope is listed
omp plugin uninstall aleph@aleph-mcp --scope user
omp plugin uninstall aleph@aleph-mcp --scope project

# Remove the marketplace only after every installed scope is gone
omp plugin marketplace remove aleph-mcp

# Claude Code
/plugin uninstall aleph@aleph-mcp
/plugin marketplace remove aleph-mcp

# Standalone tool install
uv tool uninstall aleph-mcp

# uvx cache (built environments are not removed by the above)
uv cache clean aleph-mcp
```

For a named omp profile, prefix every omp command with `omp --profile <name>`. If Aleph
was the reason you removed `claude-plugins` from `disabledProviders`, add it back to the
same list after confirming no remaining plugin needs that provider.

Then, in order:

1. Delete the server entry from any hand-written config — `.omp/mcp.json`,
   `~/.omp/agent/mcp.json`, `~/.config/opencode/opencode.json`, or the client's own file.
   An uninstalled plugin does not remove a config entry you wrote yourself, and a leftover
   entry fails loudly at launch once the command is gone.
2. Remove the credentials you no longer need: the two lines from `.env` or `~/.zshrc`, and
   on macOS `security delete-generic-password -s aleph-mcp-host -a "$USER"` and the same
   for `aleph-mcp-api-key`. Releases before this one stored a key under the plain
   `aleph-mcp` service, and a failed-Keychain error once suggested `aleph-mcp:<host>`;
   neither is read any more, so search rather than trust the two names —
   `security dump-keychain | grep -i aleph-mcp` — or a live key stays behind.
3. **Revoke the API key in Aleph itself.** Deleting a local copy does not invalidate it.
4. Restart the session, and confirm with `/mcp list` that the server is gone.


## Surface

Seventeen tools, all reads:

| Tool | Aleph endpoint | Purpose |
| --- | --- | --- |
| `list_collections` | `GET /api/2/collections` | what this key can read |
| `get_collection` | `GET /api/2/collections/<id>` | metadata + statistics; accepts a `foreign_id` |
| `search_entities` | `GET /api/2/entities` | `q` + `filter:` + facets, the main entry point; `collection` required |
| `get_entity` | `GET /api/2/entities/<id>` | one entity |
| `expand_entity` | `.../expand` | graph neighbours, grouped by property |
| `entity_tags` | `.../tags` | who else shares this phone / email / address |
| `similar_entities` | `.../similar` | probable duplicates, scored |
| `match_entity` | `POST /api/2/match` | look up a name you supply, not one already indexed; `collection` required |
| `get_profile` | `GET /api/2/profiles/<id>` | a resolved identity: constituent entities + the merged pseudo-entity |
| `profile_tags` | `.../tags` | shared values across the merged identity, not one fragment |
| `profile_similar` | `.../similar` | candidates the existing merge did not absorb |
| `expand_profile` | `.../expand` | graph neighbours of the merged identity |
| `list_entitysets` | `GET /api/2/entitysets` | curated lists, diagrams, timelines |
| `get_entityset` | `GET /api/2/entitysets/<id>` | the set's own record: type, label, curator |
| `entityset_items` | `.../entities` | members of a curated set |
| `xref_results` | `GET /api/2/collections/<id>/xref` | existing cross-reference matches (read, never trigger) |
| `get_entity_text` | entity `bodyText` / child `Page`s | bounded slice of extracted text |

Three resources: `aleph://collections`, `aleph://schemata`, `aleph://schema/{name}`.
The FollowTheMoney ontology is read from the instance's own `GET /api/2/metadata`, so it
always matches the schema version that instance indexes with — no pinned client copy.

### Design choices worth knowing

- **A search must name its collection.** `collection` is a required argument on
  `search_entities` and `match_entity`, not a defaulted one, and it is the same argument —
  same name, numeric id or `foreign_id` — on every tool that takes one. The two search
  tools also accept a list; the three that address one collection do not. Aleph answers an
  unscoped search *successfully*, so a query that meant one collection and failed to say so
  returns another collection's rows, ranked and plausible, with no error anywhere — and a
  blank value is no safer, because Aleph sanitises the filter away and answers `match_all`.
  Searching everything is available only as the exact literal `collection="*"`, which
  `search_entities` annotates in the reply's `_note`. Passing `collection_id` inside
  `filters` is refused, so one scope has exactly one spelling.
- **No raw Elasticsearch DSL.** Aleph's `q` is not raw ES: it is a lenient `query_string`,
  with structured constraints arriving as repeated `filter:<field>` arguments. The tools
  expose Aleph's own grammar instead.
- **Entity search is not fuzzy.** A misspelt or transliterated name will not match by `q`.
  The fuzzy `multi_match` overlay belongs to `CollectionsQuery`, so it applies to
  `/api/2/collections?q=` and never to `/api/2/entities?q=`. `match_entity` is the tolerant
  name-lookup path. Multi-term `q` also matches on only 66% of its terms
  (`minimum_should_match`), so precision comes from `filter:`, not from adding words.
- **Facet-first.** `search_entities(facets=[...], limit=0)` surveys a result set for
  almost no context. This matters because of the next point.
- **The 9999 ceiling is a hard error, not a silent clamp.** Aleph's `SearchQueryParser`
  quietly truncates `limit + offset` past `MAX_PAGE = 9999`, which would let a model
  believe it had paged to the end. This server refuses the call and says what to do
  instead.
- **Graph expansion has its own, much lower cap** — `ALEPH_MAX_EXPAND_ENTITIES`,
  default 200 — and it is enforced separately.
- **Text blobs are stripped from search hits.** `bodyText`, `bodyHtml`, `safeHtml`,
  `indexText` and `translatedText` never enter the model's context by accident; every
  result names what was omitted, and `get_entity_text` reads them deliberately in slices.
- **Search is always scoped to a schema branch.** `/api/2/entities` picks its
  Elasticsearch index from `filter:schema` or `filter:schemata` and returns a bare 400
  when given neither. `schemata="Thing"` is applied by default — the same value the Aleph
  UI uses — and every result reports the scope it searched under `searched`. Relationship
  schemata (`Ownership`, `Directorship`, `Payment`, `UnknownLink`) descend from `Interval`,
  not `Thing`, so they must be asked for by name.
- **Captions are derived client-side.** The instances tested serialise `caption` as `null`
  on both search hits and single-entity GETs, so the server derives it the way
  followthemoney does — from the instance's own per-schema caption ordering, with a static
  fallback. Provenance is likewise recovered from the nested `collection` object when
  `collection_id` is absent.

## Develop

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy
```

277 unit tests mock all HTTP with `respx`. The 31 tests under `tests/live/` hit a real
instance and are skipped unless `ALEPH_MCP_LIVE_TESTS=1`:

```bash
ALEPH_MCP_LIVE_TESTS=1 uv run pytest tests/live -q
```

They assert shape and contract only — never any instance's content — so they are portable
to any Aleph deployment. Four of them exist because the corresponding bug survived a
fully green mocked suite: the mandatory schema scope, the null `caption`, the nested
`collection` object, and `get_collection` answering a `foreign_id` from the collections
listing, which carries no `statistics`. Run them once against a new instance before
trusting the server there.

Both suites carry a coverage tripwire, because a registered-but-untested tool is the
failure this repo keeps hitting. `tests/test_tools.py` drives every tool through MCP
twice — once asserting it forwards every argument to the right client method and returns
that method's payload unmodified, once asserting a refusal reaches the caller as a
`ToolError` — and a tool missing from either table fails
`test_every_tool_has_a_forwarding_case` / `test_every_tool_has_a_refusal_case`. Its live
twin fails unless every tool is also driven against a real instance, and
`test_every_registered_resource_is_read_here` does the same for resources. A live case
skips — loudly, naming the missing data — when the instance holds nothing of the kind it
needs, so an empty instance cannot pass for coverage; set `ALEPH_MCP_LIVE_STRICT=1`
against an instance you know is seeded and those skips become failures instead.

## Security

The security boundary is the read-scoped Aleph credential plus the outgoing-request
allowlist in `src/aleph_mcp/readonly.py`, not the agent harness's tool permissions — see
[why read-only is enforced outside the agent](#why-read-only-and-why-it-is-enforced-outside-the-agent).

**Use the latest release.** Every install path here pins a commit SHA, so an old tree stays
installable forever, and security defects were fixed at 0.1.4, 0.1.5 and 0.1.6.
To report a vulnerability, and for what is in and out of scope, see
[`SECURITY.md`](SECURITY.md).

## License

MIT — see [`LICENSE`](LICENSE).
