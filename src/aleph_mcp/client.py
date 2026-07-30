from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from .config import Settings
from .errors import raise_for_status

# Elasticsearch `from + size` window enforced by Aleph (aleph/index/util.py MAX_PAGE).
# SearchQueryParser silently clamps beyond this; we fail loudly instead so the model
# is told to narrow by facet rather than believing it paged to the end.
MAX_PAGE = 9999

# Separate, much lower cap on graph traversal (SETTINGS.MAX_EXPAND_ENTITIES default).
MAX_EXPAND = 200

# Properties that carry whole documents. Never worth spending context on inside a
# search hit; get_entity_text exists to read them deliberately and in bounded slices.
_TEXT_BLOB_PROPS = frozenset({"bodyText", "bodyHtml", "safeHtml", "indexText", "translatedText"})

_MAX_VALUE_CHARS = 500

# httpx types query values permissively; match it so no cast is needed at the call site.
Query = list[tuple[str, str | int | float | bool | None]]

_ENTITY_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
_COLLECTION_ID = re.compile(r"^[0-9]+$")


def _check_entity_id(value: str, *, field: str = "entity_id") -> str:
    if not isinstance(value, str) or not _ENTITY_ID.match(value):
        raise ValueError(f"invalid {field}: must match [A-Za-z0-9._:-]+ (got {value!r})")
    return value


def _check_collection_id(value: str | int) -> str:
    text = str(value)
    if not _COLLECTION_ID.match(text):
        raise ValueError(
            f"invalid collection_id: expected the numeric id (got {text!r}). "
            "If you have a foreign_id such as 'my-case', call get_collection first."
        )
    return text


def _truncate(value: str) -> str:
    if len(value) <= _MAX_VALUE_CHARS:
        return value
    return value[:_MAX_VALUE_CHARS] + f"… [+{len(value) - _MAX_VALUE_CHARS} chars]"


def slim_entity(entity: dict[str, Any]) -> dict[str, Any]:
    """Strip an entity down to what is worth putting in a model's context.

    Drops document-sized text properties and truncates long values, keeping the
    identity, schema, collection and highlights intact so the model can decide what
    to fetch in full.
    """
    props: dict[str, Any] = {}
    dropped: list[str] = []
    for name, values in (entity.get("properties") or {}).items():
        if name in _TEXT_BLOB_PROPS:
            dropped.append(name)
            continue
        if isinstance(values, list):
            props[name] = [_truncate(v) if isinstance(v, str) else v for v in values]
        else:
            props[name] = values

    slim: dict[str, Any] = {
        "id": entity.get("id"),
        "schema": entity.get("schema"),
        "caption": entity.get("caption"),
        "collection_id": entity.get("collection_id"),
        "properties": props,
    }
    for optional in ("highlight", "score", "profile_id", "first_seen", "last_seen"):
        if entity.get(optional) is not None:
            slim[optional] = entity[optional]
    if dropped:
        slim["_omitted_properties"] = sorted(dropped)
    return slim


def _slim_result(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total": (payload.get("total") or {}),
        "limit": payload.get("limit"),
        "offset": payload.get("offset"),
        "results": [slim_entity(e) for e in payload.get("results") or []],
    }
    if payload.get("facets"):
        out["facets"] = payload["facets"]
    return out


class AlephClient:
    """Async, read-only wrapper around the Aleph HTTP API.

    Owns one httpx.AsyncClient; the caller closes it with aclose(). Only GET requests
    are issued, with the single exception of POST /api/2/match, which is a read
    operation that takes a JSON body. No endpoint that creates, mutates or deletes
    Aleph state is reachable through this class.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model: dict[str, Any] | None = None
        self._http = httpx.AsyncClient(
            base_url=settings.host,
            headers={
                "Authorization": f"ApiKey {settings.api_key}",
                "Accept": "application/json",
                "User-Agent": "aleph-mcp",
            },
            timeout=settings.timeout_secs,
            verify=settings.verify_tls,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- followthemoney ontology -----------------------------------------------

    async def get_model(self) -> dict[str, Any]:
        """The instance's own FollowTheMoney model, cached for the process lifetime.

        Sourced from GET /api/2/metadata so the ontology always matches the schema
        version the server actually indexes with, instead of a pinned client copy.
        """
        if self._model is None:
            payload = await self._request(
                "GET", "/api/2/metadata", context="aleph://schema", resource=True
            )
            self._model = payload.get("model") or {}
        return self._model

    async def list_schemata(self) -> dict[str, Any]:
        model = await self.get_model()
        schemata = model.get("schemata") or {}
        return {
            "count": len(schemata),
            "matchable": sorted(n for n, s in schemata.items() if s.get("matchable")),
            "edges": sorted(n for n, s in schemata.items() if s.get("edge")),
            "all": sorted(schemata),
        }

    async def get_schema(self, *, name: str) -> dict[str, Any]:
        model = await self.get_model()
        schemata = model.get("schemata") or {}
        schema = schemata.get(name)
        if schema is None:
            close = sorted(n for n in schemata if n.lower().startswith(name[:3].lower()))
            raise ValueError(
                f"unknown followthemoney schema {name!r}. "
                + (f"Did you mean one of: {', '.join(close[:10])}?" if close else "")
                + " Read aleph://schemata for the full list."
            )
        return {
            "name": name,
            "label": schema.get("label"),
            "plural": schema.get("plural"),
            "description": schema.get("description"),
            "extends": schema.get("extends"),
            "schemata": schema.get("schemata"),
            "abstract": schema.get("abstract"),
            "matchable": schema.get("matchable"),
            "generated": schema.get("generated"),
            "caption": schema.get("caption"),
            "featured": schema.get("featured"),
            "required": schema.get("required"),
            "edge": schema.get("edge"),
            "properties": {
                pname: {
                    "label": p.get("label"),
                    "type": p.get("type"),
                    "description": p.get("description"),
                    "range": p.get("range"),
                    "reverse": p.get("reverse"),
                    "stub": p.get("stub"),
                    "hidden": p.get("hidden"),
                    "matchable": p.get("matchable"),
                    "format": p.get("format"),
                }
                for pname, p in (schema.get("properties") or {}).items()
            },
            "_note": (
                "`properties` lists only what this schema declares itself; a Person also "
                "carries every property of LegalEntity and Thing. `schemata` is the full "
                "inheritance chain — read those entries for the rest. Properties with a "
                "`range` point at other entities and are what expand_entity traverses."
            ),
        }

    # -- transport -------------------------------------------------------------

    _RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    async def _request(
        self,
        method: str,
        path: str,
        *,
        context: str,
        params: Query | None = None,
        json: Any | None = None,
        resource: bool = False,
    ) -> dict[str, Any]:
        attempts = self._settings.max_retries
        query = httpx.QueryParams(params) if params else None
        resp: httpx.Response | None = None
        for attempt in range(1, attempts + 1):
            resp = await self._http.request(method, path, params=query, json=json)
            if resp.status_code not in self._RETRY_STATUS or attempt == attempts:
                break
            await asyncio.sleep(_retry_delay(resp, attempt))
        assert resp is not None
        raise_for_status(resp, context=context, resource=resource)
        data: Any = resp.json()
        if not isinstance(data, dict):
            return {"results": data}
        return data

    # -- collections -----------------------------------------------------------

    async def list_collections(
        self, *, q: str | None = None, limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        params = _page_params(limit, offset, cap=100)
        if q:
            params.append(("q", q))
        payload = await self._request(
            "GET", "/api/2/collections", context="list_collections", params=params
        )
        return {
            "total": payload.get("total"),
            "limit": payload.get("limit"),
            "offset": payload.get("offset"),
            "results": [_slim_collection(c) for c in payload.get("results") or []],
        }

    async def get_collection(self, *, collection: str) -> dict[str, Any]:
        """Fetch one collection by numeric id or by foreign_id."""
        if _COLLECTION_ID.match(str(collection)):
            payload = await self._request(
                "GET",
                f"/api/2/collections/{collection}",
                context="get_collection",
                params=[("refresh", "true")],
            )
            return _slim_collection(payload, full=True)

        listing = await self._request(
            "GET",
            "/api/2/collections",
            context="get_collection",
            params=[("filter:foreign_id", str(collection)), ("limit", "1")],
        )
        results = listing.get("results") or []
        if not results:
            raise ValueError(
                f"no collection with foreign_id {collection!r} is readable with this API key; "
                "call list_collections to see what is available"
            )
        return _slim_collection(results[0], full=True)

    # -- entity search ---------------------------------------------------------

    async def search_entities(
        self,
        *,
        q: str | None = None,
        filters: dict[str, str | list[str]] | None = None,
        schema: str | None = None,
        schemata: str | None = None,
        facets: list[str] | None = None,
        facet_size: int = 20,
        limit: int = 20,
        offset: int = 0,
        highlight: bool = False,
    ) -> dict[str, Any]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit + offset > MAX_PAGE:
            raise ValueError(
                f"limit + offset must be <= {MAX_PAGE}: Aleph cannot page past result "
                f"{MAX_PAGE} (Elasticsearch result-window limit), so deep pagination is not a "
                "way to read a whole collection. Narrow the query instead — add filters, or "
                "call this tool with facets=['schema','collection_id','countries'] and "
                "limit=0 to see how the result set breaks down, then query each slice."
            )

        params: Query = [("limit", str(limit)), ("offset", str(offset))]
        if q:
            params.append(("q", q))
        if schema:
            params.append(("filter:schema", schema))
        if schemata:
            params.append(("filter:schemata", schemata))
        for key, value in (filters or {}).items():
            for item in value if isinstance(value, list) else [value]:
                params.append((f"filter:{key}", str(item)))
        for facet in facets or []:
            params.append(("facet", facet))
            params.append((f"facet_size:{facet}", str(facet_size)))
            params.append((f"facet_total:{facet}", "true"))
        if highlight and q:
            params.append(("highlight", "true"))
            params.append(("highlight_count", "3"))

        payload = await self._request(
            "GET", "/api/2/entities", context="search_entities", params=params
        )
        result = _slim_result(payload)
        total = result.get("total") or 0
        total_count = total.get("value") if isinstance(total, dict) else total
        if isinstance(total_count, int) and total_count > MAX_PAGE:
            result["_note"] = (
                f"{total_count} matches exceed the {MAX_PAGE} pagination ceiling; only the "
                "first results are reachable. Narrow with filters or facet first."
            )
        return result

    async def get_entity(self, *, entity_id: str) -> dict[str, Any]:
        _check_entity_id(entity_id)
        payload = await self._request("GET", f"/api/2/entities/{entity_id}", context="get_entity")
        return slim_entity(payload)

    async def expand_entity(
        self, *, entity_id: str, properties: list[str] | None = None, limit: int = 50
    ) -> dict[str, Any]:
        _check_entity_id(entity_id)
        if limit < 1 or limit > MAX_EXPAND:
            raise ValueError(
                f"limit must be between 1 and {MAX_EXPAND}: graph expansion has its own, much "
                f"lower ceiling than search (ALEPH_MAX_EXPAND_ENTITIES, default {MAX_EXPAND})."
            )
        params: Query = [("limit", str(limit))]
        for prop in properties or []:
            params.append(("filter:property", prop))
        payload = await self._request(
            "GET",
            f"/api/2/entities/{entity_id}/expand",
            context="expand_entity",
            params=params,
        )
        return {
            "total": payload.get("total"),
            "results": [
                {
                    "property": group.get("property"),
                    "count": group.get("count"),
                    "entities": [slim_entity(e) for e in group.get("entities") or []],
                }
                for group in payload.get("results") or []
            ],
        }

    async def similar_entities(self, *, entity_id: str, limit: int = 20) -> dict[str, Any]:
        _check_entity_id(entity_id)
        payload = await self._request(
            "GET",
            f"/api/2/entities/{entity_id}/similar",
            context="similar_entities",
            params=_page_params(limit, 0, cap=100),
        )
        return {
            "total": payload.get("total"),
            "results": [
                {
                    "score": item.get("score"),
                    "judgement": item.get("judgement"),
                    "entity": slim_entity(item.get("entity") or {}),
                }
                for item in payload.get("results") or []
            ],
        }

    async def entity_tags(self, *, entity_id: str) -> dict[str, Any]:
        _check_entity_id(entity_id)
        return await self._request(
            "GET", f"/api/2/entities/{entity_id}/tags", context="entity_tags"
        )

    async def match_entity(
        self,
        *,
        sample: dict[str, Any],
        collection_ids: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if "schema" not in sample:
            raise ValueError(
                "sample must include a followthemoney 'schema' key, e.g. "
                '{"schema": "Person", "properties": {"name": ["Jane Doe"]}}'
            )
        params = _page_params(limit, 0, cap=100)
        for cid in collection_ids or []:
            params.append(("collection_ids", _check_collection_id(cid)))
        payload = await self._request(
            "POST", "/api/2/match", context="match_entity", params=params, json=sample
        )
        return _slim_result(payload)

    # -- curated sets and cross-referencing ------------------------------------

    async def list_entitysets(
        self,
        *,
        collection_id: str,
        set_type: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        params = _page_params(limit, 0, cap=100)
        params.append(("filter:collection_id", _check_collection_id(collection_id)))
        if set_type:
            params.append(("filter:type", set_type))
        payload = await self._request(
            "GET", "/api/2/entitysets", context="list_entitysets", params=params
        )
        return {
            "total": payload.get("total"),
            "results": [
                {
                    "id": s.get("id"),
                    "type": s.get("type"),
                    "label": s.get("label"),
                    "summary": s.get("summary"),
                    "entities": s.get("entities"),
                    "updated_at": s.get("updated_at"),
                }
                for s in payload.get("results") or []
            ],
        }

    async def entityset_items(
        self, *, entityset_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        _check_entity_id(entityset_id, field="entityset_id")
        payload = await self._request(
            "GET",
            f"/api/2/entitysets/{entityset_id}/entities",
            context="entityset_items",
            params=_page_params(limit, offset, cap=200),
        )
        return _slim_result(payload)

    async def xref_results(
        self, *, collection_id: str, limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        cid = _check_collection_id(collection_id)
        payload = await self._request(
            "GET",
            f"/api/2/collections/{cid}/xref",
            context="xref_results",
            params=_page_params(limit, offset, cap=100),
        )
        return {
            "total": payload.get("total"),
            "limit": payload.get("limit"),
            "offset": payload.get("offset"),
            "results": [
                {
                    "score": m.get("score"),
                    "judgement": m.get("judgement"),
                    "entity": slim_entity(m.get("entity") or {}),
                    "match": slim_entity(m.get("match") or {}),
                    "match_collection_id": m.get("match_collection_id"),
                }
                for m in payload.get("results") or []
            ],
        }

    # -- document text ---------------------------------------------------------

    async def get_entity_text(
        self, *, entity_id: str, offset: int = 0, limit: int = 20000
    ) -> dict[str, Any]:
        """Return a bounded slice of a document's extracted text.

        Reads `bodyText` off the entity itself; for a multi-page document the text
        lives on child `Page` entities instead, which are fetched in page order.
        """
        _check_entity_id(entity_id)
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > 200_000:
            raise ValueError("limit must be between 1 and 200000 characters")

        entity = await self._request(
            "GET", f"/api/2/entities/{entity_id}", context="get_entity_text"
        )
        body = "\n".join((entity.get("properties") or {}).get("bodyText") or [])
        source = "bodyText"

        if not body:
            pages = await self._request(
                "GET",
                "/api/2/entities",
                context="get_entity_text",
                params=[
                    ("filter:properties.document", entity_id),
                    ("filter:schema", "Page"),
                    ("limit", "500"),
                    ("sort", "properties.index:asc"),
                ],
            )
            chunks: list[str] = []
            for page in pages.get("results") or []:
                chunks.extend((page.get("properties") or {}).get("bodyText") or [])
            body = "\n\n".join(chunks)
            source = "pages"

        total = len(body)
        slice_ = body[offset : offset + limit]
        return {
            "entity_id": entity_id,
            "schema": entity.get("schema"),
            "caption": entity.get("caption"),
            "source": source,
            "offset": offset,
            "limit": limit,
            "returned_chars": len(slice_),
            "total_chars": total,
            "truncated": offset + limit < total,
            "text": slice_,
        }


def _slim_collection(c: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": c.get("id"),
        "foreign_id": c.get("foreign_id"),
        "label": c.get("label"),
        "category": c.get("category"),
        "casefile": c.get("casefile"),
        "countries": c.get("countries"),
        "updated_at": c.get("updated_at"),
        "writeable": c.get("writeable"),
    }
    if full:
        out["summary"] = c.get("summary")
        out["languages"] = c.get("languages")
        out["statistics"] = c.get("statistics")
        out["count"] = c.get("count")
    return out


def _page_params(limit: int, offset: int, *, cap: int) -> Query:
    if limit < 0 or limit > cap:
        raise ValueError(f"limit must be between 0 and {cap}")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    return [("limit", str(limit)), ("offset", str(offset))]


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(60.0, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(30.0, float(2 ** (attempt - 1)))
