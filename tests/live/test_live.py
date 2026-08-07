"""Live tests against a real Aleph instance.

Skipped unless ALEPH_MCP_LIVE_TESTS=1 and ALEPHCLIENT_HOST/ALEPHCLIENT_API_KEY (or the
ALEPH_HOST/ALEPH_API_KEY aliases) are set. Every assertion here is deliberately about
*shape and contract*, never about a particular instance's content, so the suite is
portable to any Aleph deployment.

Set ALEPH_MCP_LIVE_STRICT=1 against an instance you know is seeded: a case that would
skip for missing fixture data fails instead. Without it a run whose discovery quietly
stopped finding the profile or the documents is indistinguishable from a green one.

Two of these exist because a mocked suite could not have caught the corresponding bug:
- `/api/2/entities` rejects a query that names no schema or schemata.
- Aleph serialises `caption` as null and nests the collection object in search hits.

The bottom half drives every registered tool through the MCP boundary against the real
instance. A mocked test proves a tool matches our belief about Aleph; only this proves
the belief. Where the instance holds no data of the required kind the case skips, and
says which data would make it run — an empty instance must not read as coverage.
"""

from __future__ import annotations

import os
from typing import Any, NoReturn

import pytest
from fastmcp import Client as MCPClient
from fastmcp import FastMCP

from aleph_mcp.client import MAX_PAGE, AlephClient
from aleph_mcp.config import Settings
from aleph_mcp.readonly import ReadOnlyViolation
from aleph_mcp.server import build_server
from tests.shapes import assert_search_envelope, unfence

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("ALEPH_MCP_LIVE_TESTS") != "1",
        reason="set ALEPH_MCP_LIVE_TESTS=1 to run against a real Aleph instance",
    ),
]


def _no_fixture_data(reason: str) -> NoReturn:
    """Skip — or, under ALEPH_MCP_LIVE_STRICT=1, fail — when the instance lacks the data.

    An empty instance must not read as coverage. On a seeded instance a skip means
    discovery broke rather than that the data is absent, which is what strict mode makes
    visible.
    """
    if os.environ.get("ALEPH_MCP_LIVE_STRICT") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


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


async def test_profile_tools_accept_a_real_profile_id(live_client: AlephClient) -> None:
    """Profiles are opt-in per instance: an Aleph with no cross-referencing judged has
    none at all, so skip rather than fail. `profile_id` arrives on the search hit itself,
    which is the discovery path the tools rely on."""
    out = await live_client.search_entities(schemata="LegalEntity", limit=50)
    profile_id = next((hit["profile_id"] for hit in out["results"] if hit.get("profile_id")), None)
    if not profile_id:
        _no_fixture_data("no profile on the sampled entities; instance has no judged xref")

    profile = await live_client.get_profile(profile_id=profile_id)
    assert profile["type"] == "profile"
    assert isinstance(profile["entities"], list)
    assert "bodyText" not in profile["merged"].get("properties", {})

    expanded = await live_client.expand_profile(profile_id=profile_id, limit=5)
    assert isinstance(expanded["results"], list)

    tags = await live_client.profile_tags(profile_id=profile_id)
    assert "results" in tags

    similar = await live_client.profile_similar(profile_id=profile_id, limit=3)
    assert isinstance(similar["results"], list)

    # A profile IS an entityset, so this route 302s to the profile view. Aleph builds that
    # Location from its public UI url, which is a different host:port from the API, so the
    # hop must be reported rather than followed — this is the assertion that caught it.
    as_set = await live_client.get_entityset(entityset_id=profile_id)
    assert as_set["type"] == "profile"
    assert "get_profile" in as_set["_note"]


async def test_deep_pagination_is_refused_before_the_request(live_client: AlephClient) -> None:
    with pytest.raises(ValueError, match=str(MAX_PAGE)):
        await live_client.search_entities(limit=100, offset=MAX_PAGE - 1)


async def test_document_text_is_bounded_and_reports_truncation(
    live_client: AlephClient,
) -> None:
    out = await live_client.search_entities(schema="Pages", limit=5)
    if not out["results"]:
        _no_fixture_data("instance has no Pages documents")
    for hit in out["results"]:
        text = await live_client.get_entity_text(entity_id=hit["id"], limit=200)
        if text["total_chars"]:
            assert len(unfence(text["text"])) <= 200
            assert text["truncated"] == (text["total_chars"] > 200)
            assert text["source"] in {"bodyText", "pages"}
            return
    _no_fixture_data("no extracted text on the sampled documents")


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


async def test_write_requests_are_refused_before_the_network(live_client: AlephClient) -> None:
    """The guard, against a real host: a write never leaves the process, whatever the key can do."""
    for method, path in (
        ("POST", "/api/2/entities"),
        ("PATCH", "/api/2/collections/1"),
        ("DELETE", "/api/2/entities/x"),
        ("POST", "/api/2/collections/1/reingest"),
    ):
        with pytest.raises(ReadOnlyViolation):
            await live_client._http.request(method, path, json={})


# -- every tool, over MCP, against the real instance ---------------------------


@pytest.fixture
async def live_server():
    mcp, client = build_server(Settings())  # type: ignore[call-arg]
    try:
        yield mcp
    finally:
        await client.aclose()


@pytest.fixture
async def ids(live_client: AlephClient) -> dict[str, str | None]:
    """Real ids for the tools that need one, discovered the way a caller would.

    Discovery must not depend on which collection sorts first, nor on what happens to be in
    the first page of a large result set — both assumptions produced skips against an
    instance that did hold the data. So: ask every readable collection for its sets, and ask
    Aleph for the schema you want rather than filtering a general search for it.

    None means the instance genuinely holds nothing of that kind; the cases needing it skip,
    or fail under ALEPH_MCP_LIVE_STRICT=1.
    """
    collections = await live_client.list_collections(limit=100)
    collection_ids = [c["id"] for c in collections["results"] if c.get("id")]
    collection_id = collection_ids[0] if collection_ids else None

    entities = await live_client.search_entities(schemata="Thing", limit=50)
    hits = entities["results"]
    entity_id = hits[0]["id"] if hits else None

    # Any set type will do for get_entityset/entityset_items, but it may live in a
    # collection that is not the first one listed.
    entityset_id = None
    for cid in collection_ids:
        sets = await live_client.list_entitysets(collection_id=cid)
        if sets["results"]:
            entityset_id = sets["results"][0]["id"]
            break

    # A search hit carries `profile_id` when it belongs to one, which is the discovery path
    # the tools advertise. Failing that, a profile IS an entityset of type "profile" and its
    # entityset id *is* the profile id, so the listing route finds one the search missed.
    profile_id = next((h["profile_id"] for h in hits if h.get("profile_id")), None)
    if not profile_id:
        for cid in collection_ids:
            sets = await live_client.list_entitysets(collection_id=cid, set_type="profile")
            if sets["results"]:
                profile_id = sets["results"][0]["id"]
                break

    # Aleph returns no indexText/bodyText on search hits, so a live `Pages` row never carries
    # `_omitted_properties` and scanning general hits for one finds nothing. Ask for the
    # schema instead.
    pages = await live_client.search_entities(schema="Pages", limit=1)
    document_id = pages["results"][0]["id"] if pages["results"] else None

    return {
        "collection_id": collection_id,
        "entity_id": entity_id,
        "profile_id": profile_id,
        "document_id": document_id,
        "entityset_id": entityset_id,
    }


def _tool_arguments(name: str, ids: dict[str, str | None]) -> dict[str, Any]:
    """Arguments for one tool, or a skip naming the data the instance is missing.

    Keeping this a single mapping is what lets the tripwire below prove the live suite
    reaches every registered tool: a new tool has to appear here or the suite fails.
    """

    def need(key: str) -> str:
        value = ids[key]
        if not value:
            _no_fixture_data(f"instance has no {key} to exercise {name} against")
        return value

    match name:
        case "list_collections":
            return {"limit": 5}
        case "get_collection":
            return {"collection": need("collection_id")}
        case "search_entities":
            return {"schemata": "Thing", "facets": ["schema"], "limit": 1}
        case "get_entity" | "entity_tags":
            return {"entity_id": need("entity_id")}
        case "expand_entity":
            return {"entity_id": need("entity_id"), "limit": 5}
        case "similar_entities":
            return {"entity_id": need("entity_id"), "limit": 3}
        case "match_entity":
            return {
                "sample": {"schema": "Person", "properties": {"name": ["Jane Doe"]}},
                "limit": 3,
            }
        case "get_profile" | "profile_tags":
            return {"profile_id": need("profile_id")}
        case "profile_similar":
            return {"profile_id": need("profile_id"), "limit": 3}
        case "expand_profile":
            return {"profile_id": need("profile_id"), "limit": 5}
        case "list_entitysets":
            return {"collection_id": need("collection_id")}
        case "get_entityset" | "entityset_items":
            return {"entityset_id": need("entityset_id")}
        case "xref_results":
            return {"collection_id": need("collection_id")}
        case "get_entity_text":
            return {"entity_id": need("document_id"), "limit": 500}
    raise AssertionError(f"no live arguments defined for tool {name!r}")


LIVE_TOOL_ARGUMENTS = (
    "list_collections",
    "get_collection",
    "search_entities",
    "get_entity",
    "expand_entity",
    "entity_tags",
    "similar_entities",
    "match_entity",
    "get_profile",
    "profile_tags",
    "profile_similar",
    "expand_profile",
    "list_entitysets",
    "get_entityset",
    "entityset_items",
    "xref_results",
    "get_entity_text",
)


@pytest.mark.parametrize("tool", LIVE_TOOL_ARGUMENTS)
async def test_tool_answers_against_the_real_instance(
    live_server: FastMCP, ids: dict[str, str | None], tool: str
) -> None:
    """Aleph must accept the request we build and we must accept the response it sends.

    Asserted loosely on purpose: content varies per deployment, but a tool that 400s,
    404s or returns something the slimming path cannot walk fails here.
    """
    async with MCPClient(live_server) as mcp:
        result = await mcp.call_tool(tool, _tool_arguments(tool, ids))
    assert isinstance(result.data, dict), f"{tool} returned {type(result.data).__name__}"


async def test_live_coverage_reaches_every_registered_tool(live_server: FastMCP) -> None:
    """Tripwire: a tool added without a live case would otherwise be proven only against
    our own mocks, which is where every Aleph surprise so far has slipped through."""
    async with MCPClient(live_server) as mcp:
        registered = {t.name for t in await mcp.list_tools()}
    assert registered == set(LIVE_TOOL_ARGUMENTS)


async def test_live_responses_match_the_shape_the_mocked_suite_asserts(
    live_client: AlephClient, ids: dict[str, str | None]
) -> None:
    """Closes the mocked-vs-real drift loop.

    `assert_search_envelope` is the same helper that guards every mocked payload, so an
    Aleph field the slimmer starts leaking fails here instead of passing everywhere — the
    mocks cannot grow the field on their own.
    """
    assert_search_envelope(
        await live_client.search_entities(schemata="Thing", limit=5),
        searched={"schemata": "Thing"},
    )

    entityset_id = ids["entityset_id"]
    if not entityset_id:
        _no_fixture_data("instance has no entityset_id to check the entityset_items shape")
    assert_search_envelope(await live_client.entityset_items(entityset_id=entityset_id, limit=5))


async def test_resources_answer_against_the_real_instance(live_server: FastMCP) -> None:
    async with MCPClient(live_server) as mcp:
        listed = {str(r.uri) for r in await mcp.list_resources()}
        assert listed == {"aleph://collections", "aleph://schemata"}

        collections = await mcp.read_resource("aleph://collections")
        assert '"results"' in collections[0].text

        schemata = await mcp.read_resource("aleph://schemata")
        assert '"Ownership"' in schemata[0].text

        # Templated, so it is not in list_resources; read it directly.
        person = await mcp.read_resource("aleph://schema/Person")
        assert '"Person"' in person[0].text


async def test_get_collection_returns_statistics_from_either_branch(
    live_client: AlephClient, ids: dict[str, str | None]
) -> None:
    """Regression: the foreign_id branch answered from the collections listing, which
    carries no `statistics`, so the same collection came back with stats by id and
    without them by foreign_id — the one thing get_collection adds over list_collections.
    """
    collection_id = ids["collection_id"]
    if not collection_id:
        pytest.skip("instance has no readable collection")
    by_id = await live_client.get_collection(collection=collection_id)
    foreign_id = by_id.get("foreign_id")
    if not foreign_id:
        pytest.skip("collection has no foreign_id")

    by_foreign_id = await live_client.get_collection(collection=foreign_id)
    assert by_foreign_id["id"] == by_id["id"]
    assert by_foreign_id["statistics"] is not None
    assert set(by_foreign_id["statistics"]) == set(by_id["statistics"])
