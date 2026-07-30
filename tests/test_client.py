from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from aleph_mcp.client import MAX_EXPAND, MAX_PAGE, AlephClient, slim_entity


def _query(request: httpx.Request) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(str(request.url)).query, keep_blank_values=True)


def _entity(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "e1",
        "schema": "Person",
        "caption": "Jane Doe",
        "collection_id": "42",
        "properties": {"name": ["Jane Doe"]},
    }
    base.update(kw)
    return base


# -- slimming ------------------------------------------------------------------


def test_slim_entity_drops_text_blobs_and_reports_them() -> None:
    out = slim_entity(
        _entity(properties={"name": ["Jane"], "bodyText": ["x" * 5000], "indexText": ["y"]})
    )
    assert "bodyText" not in out["properties"]
    assert out["_omitted_properties"] == ["bodyText", "indexText"]
    assert out["properties"]["name"] == ["Jane"]


def test_slim_entity_truncates_long_values() -> None:
    out = slim_entity(_entity(properties={"summary": ["z" * 2000]}))
    value = out["properties"]["summary"][0]
    assert value.endswith("chars]")
    assert len(value) < 600


def test_slim_entity_keeps_highlight_and_score() -> None:
    out = slim_entity(_entity(highlight=["…hit…"], score=3.5))
    assert out["highlight"] == ["…hit…"]
    assert out["score"] == 3.5


# -- auth / transport ----------------------------------------------------------


async def test_sends_apikey_header(client: AlephClient, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": [], "total": 0})
    )
    await client.list_collections()
    assert route.calls.last.request.headers["Authorization"] == "ApiKey test_key"


async def test_retries_on_429_then_succeeds(
    client: AlephClient, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("aleph_mcp.client.asyncio.sleep", _no_sleep)
    route = respx_mock.get("/api/2/collections").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"results": [], "total": 0}),
        ]
    )
    await client.list_collections()
    assert route.call_count == 2


async def test_gives_up_after_max_retries(
    client: AlephClient, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("aleph_mcp.client.asyncio.sleep", _no_sleep)
    route = respx_mock.get("/api/2/collections").mock(return_value=httpx.Response(503))
    with pytest.raises(ToolError, match="unexpected HTTP 503"):
        await client.list_collections()
    assert route.call_count == 4  # Settings.max_retries default


# -- collections ---------------------------------------------------------------


async def test_get_collection_by_numeric_id(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/collections/42").mock(
        return_value=httpx.Response(
            200, json={"id": "42", "foreign_id": "case", "label": "Case", "statistics": {}}
        )
    )
    out = await client.get_collection(collection="42")
    assert out["id"] == "42"
    assert "statistics" in out


async def test_get_collection_by_foreign_id(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "42", "foreign_id": "case", "label": "Case"}]}
        )
    )
    out = await client.get_collection(collection="case")
    assert out["id"] == "42"
    assert ("filter:foreign_id", "case") in _query(route.calls.last.request)


async def test_get_collection_unknown_foreign_id_is_actionable(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(ValueError, match="list_collections"):
        await client.get_collection(collection="nope")


# -- search --------------------------------------------------------------------


async def test_search_builds_filter_and_facet_params(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.search_entities(
        q="acme",
        filters={"collection_id": "42", "countries": ["ru", "cy"]},
        schema="Company",
        facets=["schema"],
        limit=0,
    )
    q = _query(route.calls.last.request)
    assert ("q", "acme") in q
    assert ("filter:collection_id", "42") in q
    assert ("filter:countries", "ru") in q
    assert ("filter:countries", "cy") in q
    assert ("filter:schema", "Company") in q
    assert ("facet", "schema") in q
    assert ("facet_size:schema", "20") in q
    assert ("facet_total:schema", "true") in q


async def test_search_rejects_deep_pagination(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="facets"):
        await client.search_entities(limit=50, offset=MAX_PAGE)


async def test_search_allows_the_exact_ceiling(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.search_entities(limit=9, offset=MAX_PAGE - 9)


async def test_search_notes_unreachable_tail(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 50000}})
    )
    out = await client.search_entities(q="a")
    assert "pagination ceiling" in out["_note"]


async def test_search_strips_text_from_hits(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": {"value": 1},
                "results": [_entity(properties={"name": ["Jane"], "bodyText": ["x" * 10000]})],
            },
        )
    )
    out = await client.search_entities(q="jane")
    assert "bodyText" not in out["results"][0]["properties"]


async def test_highlight_only_when_query_present(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.search_entities(highlight=True)
    assert ("highlight", "true") not in _query(route.calls.last.request)


# -- entity, expand ------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a b", "e1/x", ""])
async def test_entity_id_validation(client: AlephClient, bad: str) -> None:
    with pytest.raises(ValueError, match="invalid entity_id"):
        await client.get_entity(entity_id=bad)


async def test_expand_rejects_limit_above_cap(client: AlephClient) -> None:
    with pytest.raises(ValueError, match=str(MAX_EXPAND)):
        await client.expand_entity(entity_id="e1", limit=MAX_EXPAND + 1)


async def test_expand_passes_property_filters_and_slims(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities/e1/expand").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "property": "ownershipOwner",
                        "count": 7,
                        "entities": [_entity(properties={"bodyText": ["x"], "name": ["A"]})],
                    }
                ],
            },
        )
    )
    out = await client.expand_entity(entity_id="e1", properties=["ownershipOwner"], limit=10)
    assert ("filter:property", "ownershipOwner") in _query(route.calls.last.request)
    assert out["results"][0]["count"] == 7
    assert "bodyText" not in out["results"][0]["entities"][0]["properties"]


# -- match ---------------------------------------------------------------------


async def test_match_requires_schema(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="schema"):
        await client.match_entity(sample={"properties": {"name": ["x"]}})


async def test_match_posts_sample(client: AlephClient, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/api/2/match").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.match_entity(
        sample={"schema": "Person", "properties": {"name": ["Jane"]}}, collection_ids=["42"]
    )
    assert ("collection_ids", "42") in _query(route.calls.last.request)


async def test_collection_id_validation_rejects_foreign_id(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="get_collection"):
        await client.xref_results(collection_id="my-case")


# -- document text -------------------------------------------------------------


async def test_get_entity_text_from_body_text(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/d1").mock(
        return_value=httpx.Response(
            200,
            json=_entity(id="d1", schema="PlainText", properties={"bodyText": ["abcdefghij"]}),
        )
    )
    out = await client.get_entity_text(entity_id="d1", offset=2, limit=3)
    assert out["text"] == "cde"
    assert out["total_chars"] == 10
    assert out["truncated"] is True
    assert out["source"] == "bodyText"


async def test_get_entity_text_falls_back_to_pages(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/d2").mock(
        return_value=httpx.Response(200, json=_entity(id="d2", schema="Pages", properties={}))
    )
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"properties": {"bodyText": ["page one"]}},
                    {"properties": {"bodyText": ["page two"]}},
                ]
            },
        )
    )
    out = await client.get_entity_text(entity_id="d2")
    q = _query(route.calls.last.request)
    assert ("filter:properties.document", "d2") in q
    assert ("filter:schema", "Page") in q
    assert out["source"] == "pages"
    assert out["text"] == "page one\n\npage two"
    assert out["truncated"] is False


async def test_get_entity_text_rejects_absurd_limit(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="200000"):
        await client.get_entity_text(entity_id="d1", limit=10**9)


# -- ontology ------------------------------------------------------------------


async def test_get_schema_is_cached_after_first_fetch(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/metadata").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": {
                    "schemata": {
                        "Person": {
                            "label": "Person",
                            "matchable": True,
                            "schemata": ["Person", "LegalEntity", "Thing"],
                            "properties": {"name": {"label": "Name", "type": "name"}},
                        },
                        "Ownership": {
                            "label": "Ownership",
                            "edge": {"source": "owner", "target": "asset", "directed": True},
                            "properties": {},
                        },
                    }
                }
            },
        )
    )
    person = await client.get_schema(name="Person")
    listing = await client.list_schemata()
    assert route.call_count == 1
    assert person["properties"]["name"]["type"] == "name"
    assert "inheritance chain" in person["_note"]
    assert listing["edges"] == ["Ownership"]
    assert listing["matchable"] == ["Person"]


async def test_unknown_schema_suggests_alternatives(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(
        return_value=httpx.Response(200, json={"model": {"schemata": {"Person": {}}}})
    )
    with pytest.raises(ValueError, match="Did you mean"):
        await client.get_schema(name="Persson")
