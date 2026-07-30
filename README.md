# aleph-mcp

A **read-only** [MCP](https://modelcontextprotocol.io) server over the
[Aleph](https://github.com/alephdata/aleph) HTTP API, so an LLM agent can search,
pivot and read an investigative dataset without being able to change it.

Sibling tools: [`aleph-coldbackup`](../aleph-coldbackup) (bulk export of a collection)
and [`datashare-mcp`](../datashare-mcp) (the same idea for ICIJ Datashare).

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
trying to page through it. For genuine bulk export use `aleph-coldbackup` with a
write-scoped key, run by a human.

## Install

Requires Python ≥ 3.12 and [`uv`](https://github.com/astral-sh/uv).

```bash
uv tool install aleph-mcp        # or, from a checkout:
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

## Wire it up

opencode — `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "aleph": {
      "type": "local",
      "command": ["uvx", "aleph-mcp"],
      "enabled": true,
      "environment": {
        "ALEPHCLIENT_HOST": "https://aleph.example.org",
        "ALEPHCLIENT_API_KEY": "{env:ALEPHCLIENT_API_KEY}"
      }
    }
  }
}
```

Tools then appear to the model as `aleph_search_entities`, `aleph_expand_entity`, and so
on (`sanitize(server) + "_" + sanitize(tool)`). Claude Code / any stdio MCP client:
the same command in `.mcp.json`.

## Surface

Twelve tools, all reads:

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
| `list_entitysets` | `GET /api/2/entitysets` | curated lists, diagrams, timelines |
| `entityset_items` | `.../entities` | members of a curated set |
| `xref_results` | `GET /api/2/collections/<id>/xref` | existing cross-reference matches (read, never trigger) |
| `get_entity_text` | entity `bodyText` / child `Page`s | bounded slice of extracted text |

Three resources: `aleph://collections`, `aleph://schemata`, `aleph://schema/{name}`.
The FollowTheMoney ontology is read from the instance's own `GET /api/2/metadata`, so it
always matches the schema version that instance indexes with — no pinned client copy.

### Design choices worth knowing

- **No raw Elasticsearch DSL.** Aleph's `q` is not raw ES: it is a lenient `query_string`
  *plus* a fuzzy `multi_match` boost, with structured constraints arriving as repeated
  `filter:<field>` arguments. The tools expose Aleph's own grammar instead.
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

67 unit tests mock all HTTP with `respx`. The 8 tests under `tests/live/` hit a real
instance and are skipped unless `ALEPH_MCP_LIVE_TESTS=1`:

```bash
ALEPH_MCP_LIVE_TESTS=1 uv run pytest tests/live -q
```

They assert shape and contract only — never any instance's content — so they are portable
to any Aleph deployment. Three of them exist because the corresponding bug survived a
fully green mocked suite: the mandatory schema scope, the null `caption`, and the nested
`collection` object. Run them once against a new instance before trusting the server there.

## License

MIT
