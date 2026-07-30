"""Live tests against a real Aleph instance.

Skipped unless ALEPH_MCP_LIVE_TESTS=1 and ALEPHCLIENT_HOST/ALEPHCLIENT_API_KEY (or the
ALEPH_HOST/ALEPH_API_KEY aliases) are set. Every assertion here is deliberately about
*shape and contract*, never about a particular instance's content, so the suite is
portable to any Aleph deployment.

Two of these exist because a mocked suite could not have caught the corresponding bug:
- `/api/2/entities` rejects a query that names no schema or schemata.
- Aleph serialises `caption` as null and nests the collection object in search hits.
"""

from __future__ import annotations

import os

import pytest

from aleph_mcp.client import MAX_PAGE, AlephClient
from aleph_mcp.config import Settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("ALEPH_MCP_LIVE_TESTS") != "1",
        reason="set ALEPH_MCP_LIVE_TESTS=1 to run against a real Aleph instance",
    ),
]


@pytest.fixture
async def live_client():
    client = AlephClient(Settings())  # type: ignore[call-arg]
    yield client
    await client.aclose()


async def test_can_authenticate_and_list_collections(live_client: AlephClient) -> None:
    out = await live_client.list_collections(limit=5)
    assert isinstance(out["results"], list)
    assert out["total"] is not None


async def test_search_without_a_schema_is_accepted(live_client: AlephClient) -> None:
    """Regression: Aleph 400s with 'No schema is specified for the query.'"""
    out = await live_client.search_entities(facets=["schema"], limit=0)
    assert out["searched"] == {"schemata": "Thing"}
    assert "schema" in out["facets"]


async def test_search_hits_carry_caption_and_collection(live_client: AlephClient) -> None:
    """Regression: live Aleph returns caption=null and nests `collection`."""
    out = await live_client.search_entities(schema="Person", limit=5)
    if not out["results"]:
        pytest.skip("instance has no Person entities")
    hit = out["results"][0]
    assert hit["caption"], "caption must be derived when the server omits it"
    assert hit["collection_id"], "provenance must survive slimming"


async def test_expand_and_tags_accept_a_real_entity_id(live_client: AlephClient) -> None:
    out = await live_client.search_entities(schema="Person", limit=1)
    if not out["results"]:
        pytest.skip("instance has no Person entities")
    entity_id = out["results"][0]["id"]

    expanded = await live_client.expand_entity(entity_id=entity_id, limit=5)
    assert isinstance(expanded["results"], list)

    tags = await live_client.entity_tags(entity_id=entity_id)
    assert "results" in tags

    similar = await live_client.similar_entities(entity_id=entity_id, limit=3)
    assert isinstance(similar["results"], list)


async def test_deep_pagination_is_refused_before_the_request(live_client: AlephClient) -> None:
    with pytest.raises(ValueError, match=str(MAX_PAGE)):
        await live_client.search_entities(limit=100, offset=MAX_PAGE - 1)


async def test_document_text_is_bounded_and_reports_truncation(
    live_client: AlephClient,
) -> None:
    out = await live_client.search_entities(schema="Pages", limit=5)
    if not out["results"]:
        pytest.skip("instance has no Pages documents")
    for hit in out["results"]:
        text = await live_client.get_entity_text(entity_id=hit["id"], limit=200)
        if text["total_chars"]:
            assert len(text["text"]) <= 200
            assert text["truncated"] == (text["total_chars"] > 200)
            assert text["source"] in {"bodyText", "pages"}
            return
    pytest.skip("no extracted text on the sampled documents")


async def test_ontology_comes_from_the_instance(live_client: AlephClient) -> None:
    listing = await live_client.list_schemata()
    assert listing["count"] > 0
    assert "Ownership" in listing["edges"]

    ownership = await live_client.get_schema(name="Ownership")
    assert ownership["edge"]["source"] == "owner"
    assert ownership["edge"]["target"] == "asset"


async def test_no_write_endpoint_is_reachable(live_client: AlephClient) -> None:
    """The client exposes no mutation method; assert that stays true."""
    forbidden = ("delete", "create", "write", "ingest", "upload", "flush", "reingest", "bulk")
    methods = [m for m in dir(live_client) if not m.startswith("_")]
    assert not [m for m in methods if any(word in m for word in forbidden)], methods
