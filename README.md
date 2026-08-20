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

Requires Python ≥ 3.12 and [`uv`](https://github.com/astral-sh/uv).

```bash
# Pin a release commit: this server is handed your Aleph key, and an unpinned git+ spec
# builds and runs whatever the branch head happens to be. Latest tag: v0.1.6.
uv tool install git+https://github.com/sapran/aleph-mcp.git@<commit-sha>

# Or, from a checkout:
uv sync --all-extras
```

## Configure

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `ALEPHCLIENT_HOST` | yes | — | Site root, e.g. `https://aleph.occrp.org`. A `/api/2` suffix is tolerated and stripped. |
| `ALEPHCLIENT_API_KEY` | yes | — | Aleph API key. Use a READ-only role. |
| `ALEPH_MCP_TIMEOUT_SECS` | no | `60` | Per-request HTTP timeout. |
| `ALEPH_MCP_MAX_RETRIES` | no | `4` | Attempts per request on 429/5xx, honouring `Retry-After`. |
| `ALEPH_MCP_VERIFY_TLS` | no | `true` | Set `false` for a self-signed instance. |

`ALEPHCLIENT_HOST` / `ALEPHCLIENT_API_KEY` are deliberately the same names upstream
`alephclient` and `aleph-coldbackup` read, so one exported key serves all three.

Missing required variables cause exit code 2 with a message on stderr, visible in the MCP
client's logs.

### Where to put them

Both variables must reach the server's process environment; the server reads nothing else.

- **omp** autoloads `.env` into its own environment at startup, and an stdio MCP child
  inherits it. Precedence, highest first: inherited process environment → `<cwd>/.env` →
  `~/.omp/agent/.env` → `~/.omp/.env` → `~/.env`; a variable already set is never
  overwritten by a later file. Put the two lines in `~/.omp/.env` for every project, or
  `<project>/.env` for one, then `chmod 600` the file.
- **Every other harness** — Claude Code, opencode, anything spawning the server over stdio
  — needs them exported from your shell rc (`~/.zshrc`), or set in an `env` block on that
  client's own MCP entry, accepting that the literal value then lives in that config file.

Never commit the key: `.gitignore` already lists `.env`.

## Wire it up

### omp and Claude Code (plugin)

This repository is itself a plugin marketplace, so one install delivers the server and the
`aleph-entity-graph` method skill together:

```bash
omp plugin marketplace add sapran/aleph-mcp
omp plugin install aleph@aleph-mcp
```

Claude Code: `/plugin marketplace add sapran/aleph-mcp`, then
`/plugin install aleph@aleph-mcp`.

The plugin namespaces its server as `aleph:mcp`, so tools reach the model as
`mcp__aleph_mcp_<tool>` — e.g. `mcp__aleph_mcp_search_entities`. Credentials, pinning,
several Aleph instances and running from a checkout:
[`plugins/aleph/README.md`](plugins/aleph/README.md).

### Any stdio MCP client (`mcp.json`)

```json
{
  "mcpServers": {
    "aleph": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/sapran/aleph-mcp.git@<commit-sha>", "aleph-mcp"]
    }
  }
}
```

No `env` block — credentials come from the environment the client itself runs in. Under omp
this form is not plugin-namespaced, so its tools are `mcp__aleph_<tool>`. Pin `@<commit-sha>`
to a full commit: an unpinned `git+` spec builds and runs whatever the branch head is at
launch, in a process you have just handed your Aleph key.

### opencode

`~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "aleph": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/sapran/aleph-mcp.git@<commit-sha>", "aleph-mcp"],
      "enabled": true,
      "environment": {
        "ALEPHCLIENT_HOST": "https://aleph.example.org",
        "ALEPHCLIENT_API_KEY": "{env:ALEPHCLIENT_API_KEY}"
      }
    }
  }
}
```

Tools then appear to the model as `aleph_search_entities`, `aleph_expand_entity`, and so on
(`sanitize(server) + "_" + sanitize(tool)`).

The `--from git+…` spec is required on every path above: `aleph-mcp` is not published to
PyPI, so a bare `uvx aleph-mcp` resolves nothing.

## Surface

Seventeen tools, all reads:

| Tool | Aleph endpoint | Purpose |
| --- | --- | --- |
| `list_collections` | `GET /api/2/collections` | what this key can read |
| `get_collection` | `GET /api/2/collections/<id>` | metadata + statistics; accepts a `foreign_id` |
| `search_entities` | `GET /api/2/entities` | `q` + `filter:` + facets, the main entry point |
| `get_entity` | `GET /api/2/entities/<id>` | one entity |
| `expand_entity` | `.../expand` | graph neighbours, grouped by property |
| `entity_tags` | `.../tags` | who else shares this phone / email / address |
| `similar_entities` | `.../similar` | probable duplicates, scored |
| `match_entity` | `POST /api/2/match` | look up a name you supply, not one already indexed |
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

**Use 0.1.5 or later.** Every install path here pins a commit SHA, so older trees stay
installable, and two credential-handling defects were fixed at 0.1.4 and 0.1.5. To report
a vulnerability, and for what is in and out of scope, see [`SECURITY.md`](SECURITY.md).

## License

MIT — see [`LICENSE`](LICENSE).
