from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from aleph_mcp.client import (
    MAX_EXPAND,
    MAX_PAGE,
    AlephClient,
    derive_caption,
    slim_entity,
)


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
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "42", "foreign_id": "case", "label": "Case"}]}
        )
    )
    fetch = respx_mock.get("/api/2/collections/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "42",
                "foreign_id": "case",
                "label": "Case",
                "statistics": {"schema": {"values": {"Person": 3}}},
            },
        )
    )
    out = await client.get_collection(collection="case")
    assert out["id"] == "42"
    assert ("filter:foreign_id", "case") in _query(lookup.calls.last.request)
    assert fetch.call_count == 1


async def test_foreign_id_lookup_still_returns_statistics(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Regression: the listing endpoint carries no `statistics`, so answering the
    foreign_id branch straight from the listing hit returned `statistics: null` while
    the numeric branch returned the real block. Same tool, same promise, both branches."""
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "42", "foreign_id": "case"}]})
    )
    respx_mock.get("/api/2/collections/42").mock(
        return_value=httpx.Response(
            200, json={"id": "42", "statistics": {"schema": {"values": {"Person": 3}}}}
        )
    )
    by_fid = await client.get_collection(collection="case")
    by_id = await client.get_collection(collection="42")
    assert by_fid["statistics"] == by_id["statistics"]
    assert by_fid["statistics"]["schema"]["values"]["Person"] == 3


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
    assert "UNENUMERATED" in out["_note"]


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


# -- profiles ------------------------------------------------------------------


async def test_expand_profile_rejects_limit_above_cap(client: AlephClient) -> None:
    with pytest.raises(ValueError, match=str(MAX_EXPAND)):
        await client.expand_profile(profile_id="p1", limit=MAX_EXPAND + 1)


async def test_expand_profile_passes_property_filters_and_slims(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/profiles/p1/expand").mock(
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
    out = await client.expand_profile(profile_id="p1", properties=["ownershipOwner"], limit=10)
    assert ("filter:property", "ownershipOwner") in _query(route.calls.last.request)
    assert out["results"][0]["count"] == 7
    assert "bodyText" not in out["results"][0]["entities"][0]["properties"]


async def test_get_profile_slims_the_merged_entity(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """`merged` combines the profile's constituents, so a merged-in Document drags its
    bodyText along. It has to go through slim_entity like any other entity."""
    respx_mock.get("/api/2/profiles/p1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "p1",
                "type": "profile",
                "label": "Jane Doe",
                "collection": {"id": "42"},
                "entities": ["e1", "e2"],
                "merged": _entity(properties={"bodyText": ["x" * 50], "name": ["Jane Doe"]}),
            },
        )
    )
    out = await client.get_profile(profile_id="p1")
    assert out["entities"] == ["e1", "e2"]
    assert out["collection_id"] == "42"
    assert "bodyText" not in out["merged"]["properties"]
    assert out["merged"]["_omitted_properties"] == ["bodyText"]


async def test_get_profile_drops_the_latinized_block(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """ProfileSerializer adds a transliteration of every name already in `properties`."""
    respx_mock.get("/api/2/profiles/p1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "p1",
                "type": "profile",
                "merged": _entity(),
                "latinized": {"name": ["Zhanna Doe"]},
            },
        )
    )
    out = await client.get_profile(profile_id="p1")
    assert "latinized" not in out
    assert "latinized" not in out["merged"]


async def test_profile_tags_passes_the_envelope_through(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    payload = {"status": "ok", "total": 1, "results": [{"field": "phones", "count": 3}]}
    respx_mock.get("/api/2/profiles/p1/tags").mock(return_value=httpx.Response(200, json=payload))
    assert await client.profile_tags(profile_id="p1") == payload


async def test_profile_similar_reports_score_and_judgement(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/profiles/p1/similar").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [{"score": 4.5, "judgement": None, "entity": _entity()}],
            },
        )
    )
    out = await client.profile_similar(profile_id="p1")
    assert out["results"][0]["score"] == 4.5
    assert out["results"][0]["judgement"] is None
    assert out["results"][0]["entity"]["id"] == "e1"


async def test_get_entityset_reports_a_profile_without_following_the_redirect(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Aleph 302s this route to the profile view, but builds the Location from its
    configured PUBLIC UI url — a different host:port from the API on a real deployment,
    which strips auth and 403s. Verified live: Location was localhost:8080 for an API on
    :5000. So the redirect must be read, not followed."""
    route = respx_mock.get("/api/2/entitysets/p1").mock(
        return_value=httpx.Response(
            302, headers={"Location": "http://ui.example:8080/api/2/profiles/p1"}
        )
    )
    followed = respx_mock.get("http://ui.example:8080/api/2/profiles/p1").mock(
        return_value=httpx.Response(200, json={"id": "p1", "type": "profile"})
    )
    out = await client.get_entityset(entityset_id="p1")
    assert out["type"] == "profile"
    assert out["id"] == "p1"
    assert "get_profile" in out["_note"]
    assert route.call_count == 1
    assert followed.call_count == 0, "the redirect must not be followed off the API host"


async def test_get_entityset_adds_detail_fields_a_listing_omits(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entitysets/es1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "es1",
                "type": "diagram",
                "label": "Network",
                "layout": {"vertices": []},
                "created_at": "2024-01-01",
                "role_id": "9",
                "collection": {"id": "42"},
            },
        )
    )
    out = await client.get_entityset(entityset_id="es1")
    assert out["collection_id"] == "42"
    assert out["role_id"] == "9"
    assert out["layout"] == {"vertices": []}
    assert "_note" not in out


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


# -- mandatory schema scope (regression: live 400 "No schema is specified") -----


async def test_search_applies_default_schemata_when_none_given(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    out = await client.search_entities(q="acme")
    assert ("filter:schemata", "Thing") in _query(route.calls.last.request)
    assert out["searched"] == {"schemata": "Thing"}


async def test_explicit_schemata_wins_over_the_default(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    out = await client.search_entities(schemata="Interval")
    q = _query(route.calls.last.request)
    assert ("filter:schemata", "Interval") in q
    assert ("filter:schemata", "Thing") not in q
    assert out["searched"] == {"schemata": "Interval"}


async def test_exact_schema_suppresses_the_schemata_default(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    out = await client.search_entities(schema="Ownership")
    q = _query(route.calls.last.request)
    assert ("filter:schema", "Ownership") in q
    assert not [v for k, v in q if k == "filter:schemata"]
    assert out["searched"] == {"schema": "Ownership"}


# -- caption / provenance (regression: live Aleph returns caption=null) ---------


def test_derive_caption_uses_fallback_order_when_no_model() -> None:
    assert derive_caption({"schema": "Person", "properties": {"name": ["Jane"]}}) == "Jane"
    assert derive_caption({"schema": "Document", "properties": {"fileName": ["a.pdf"]}}) == "a.pdf"


def test_derive_caption_prefers_the_schema_declared_order() -> None:
    schemata = {"LegalEntity": {"caption": ["registrationNumber", "name"]}}
    entity = {
        "schema": "LegalEntity",
        "properties": {"name": ["Acme"], "registrationNumber": ["RU-1"]},
    }
    assert derive_caption(entity, schemata) == "RU-1"
    assert derive_caption(entity) == "Acme"  # fallback order prefers name


def test_derive_caption_keeps_a_server_supplied_caption() -> None:
    assert derive_caption({"caption": "Given", "properties": {"name": ["Other"]}}) == "Given"


def test_derive_caption_returns_none_when_nothing_matches() -> None:
    assert derive_caption({"schema": "Page", "properties": {"index": [3]}}) is None


def test_slim_entity_reads_the_nested_collection_object() -> None:
    out = slim_entity({"id": "e1", "schema": "Person", "collection": {"id": 583, "label": "x"}})
    assert out["collection_id"] == "583"


async def test_search_derives_captions_from_the_instance_model(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(
        return_value=httpx.Response(
            200, json={"model": {"schemata": {"Person": {"caption": ["name"]}}}}
        )
    )
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "id": "p1",
                        "schema": "Person",
                        "caption": None,
                        "collection": {"id": 583},
                        "properties": {"name": ["Jane Doe"]},
                    }
                ],
            },
        )
    )
    out = await client.search_entities(schema="Person")
    hit = out["results"][0]
    assert hit["caption"] == "Jane Doe"
    assert hit["collection_id"] == "583"


# -- listing, pivots and cross-referencing -------------------------------------
#
# These six methods were reached only incidentally, by the read-only tripwires that
# drive every endpoint to prove none of them writes. Nothing asserted what they give
# back, so any reshaping regression in them was invisible.


async def test_list_collections_slims_and_passes_the_label_filter(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "limit": 30,
                "offset": 0,
                "results": [
                    {
                        "id": "42",
                        "foreign_id": "case",
                        "label": "Case files",
                        "category": "casefile",
                        "casefile": True,
                        "countries": ["ua"],
                        "updated_at": "2024-01-01T00:00:00",
                        "writeable": False,
                        "links": {"ui": "https://aleph.test/datasets/42"},
                        "secret": True,
                    }
                ],
            },
        )
    )
    out = await client.list_collections(q="case")
    assert ("q", "case") in _query(route.calls.last.request)
    assert (out["total"], out["limit"], out["offset"]) == (1, 30, 0)
    hit = out["results"][0]
    assert hit["id"] == "42"
    assert hit["countries"] == ["ua"]
    # The listing view carries no statistics, so it must not claim one, and the
    # server's own bookkeeping is not worth a model's context.
    assert "statistics" not in hit
    assert "links" not in hit


async def test_list_collections_omits_the_query_when_none_given(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    await client.list_collections()
    assert [k for k, _ in _query(route.calls.last.request)] == ["limit", "offset"]


async def test_list_collections_rejects_a_limit_above_the_listing_cap(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(ValueError, match="100"):
        await client.list_collections(limit=101)
    assert route.call_count == 0


async def test_entity_tags_passes_the_pivot_envelope_through(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The tags payload is already minimal and its `id` values are the queries to run
    next, so it is deliberately not slimmed. Guard that it stays untouched."""
    payload = {
        "status": "ok",
        "total": 2,
        "results": [
            {"id": "name:jane-doe", "field": "names", "value": "Jane Doe", "count": 3},
            {"id": "mailto:j@x.test", "field": "emails", "value": "j@x.test", "count": 7},
        ],
    }
    route = respx_mock.get("/api/2/entities/e1/tags").mock(
        return_value=httpx.Response(200, json=payload)
    )
    assert await client.entity_tags(entity_id="e1") == payload
    assert route.call_count == 1


async def test_similar_entities_reports_score_judgement_and_a_slim_entity(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities/e1/similar").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "score": 4.5,
                        "judgement": "positive",
                        "entity": _entity(
                            id="e2", properties={"name": ["Jane Doe"], "indexText": ["huge"]}
                        ),
                    }
                ],
            },
        )
    )
    out = await client.similar_entities(entity_id="e1", limit=5)
    assert ("limit", "5") in _query(route.calls.last.request)
    hit = out["results"][0]
    assert (hit["score"], hit["judgement"]) == (4.5, "positive")
    assert hit["entity"]["id"] == "e2"
    assert "indexText" not in hit["entity"]["properties"]


async def test_similar_entities_survives_a_result_with_no_entity(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1/similar").mock(
        return_value=httpx.Response(200, json={"total": 1, "results": [{"score": 1.0}]})
    )
    out = await client.similar_entities(entity_id="e1")
    hit = out["results"][0]
    assert hit["score"] == 1.0
    assert hit["judgement"] is None
    assert hit["entity"]["id"] is None
    assert hit["entity"]["properties"] == {}


async def test_list_entitysets_filters_by_collection_and_type(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entitysets").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "id": "es1",
                        "type": "diagram",
                        "label": "Network",
                        "summary": "who pays whom",
                        "entities": ["e1", "e2"],
                        "updated_at": "2024-01-01T00:00:00",
                        "role": {"name": "Curator"},
                    }
                ],
            },
        )
    )
    out = await client.list_entitysets(collection_id="42", set_type="diagram")
    q = _query(route.calls.last.request)
    assert ("filter:collection_id", "42") in q
    assert ("filter:type", "diagram") in q
    hit = out["results"][0]
    assert (hit["id"], hit["type"], hit["label"]) == ("es1", "diagram", "Network")
    assert hit["summary"] == "who pays whom"


async def test_list_entitysets_rejects_a_foreign_id(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="numeric id"):
        await client.list_entitysets(collection_id="my-case")


async def test_entityset_items_slims_and_pages(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entitysets/es1/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [_entity(properties={"name": ["Jane"], "bodyText": ["huge"]})],
            },
        )
    )
    out = await client.entityset_items(entityset_id="es1", limit=10, offset=5)
    q = _query(route.calls.last.request)
    assert ("limit", "10") in q and ("offset", "5") in q
    assert out["total"] == 1
    assert out["results"][0]["_omitted_properties"] == ["bodyText"]


async def test_entityset_items_refuses_a_limit_above_the_cap(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entitysets/es1/entities").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(ValueError, match="200"):
        await client.entityset_items(entityset_id="es1", limit=201)
    assert route.call_count == 0


async def test_xref_results_pairs_both_sides_of_the_match(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections/42/xref").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "limit": 30,
                "offset": 0,
                "results": [
                    {
                        "score": 3.25,
                        "judgement": "unsure",
                        "entity": _entity(id="e1"),
                        "match": _entity(
                            id="m1", properties={"name": ["Jane Doe"], "bodyText": ["huge"]}
                        ),
                        "match_collection_id": "77",
                    }
                ],
            },
        )
    )
    out = await client.xref_results(collection_id="42", limit=30)
    assert ("limit", "30") in _query(route.calls.last.request)
    hit = out["results"][0]
    assert (hit["score"], hit["judgement"]) == (3.25, "unsure")
    # Provenance is the whole point of an xref hit: which collection the match is from.
    assert hit["match_collection_id"] == "77"
    assert hit["entity"]["id"] == "e1"
    assert hit["match"]["id"] == "m1"
    assert "bodyText" not in hit["match"]["properties"]


async def test_xref_results_rejects_a_foreign_id(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="numeric id"):
        await client.xref_results(collection_id="my-case")
