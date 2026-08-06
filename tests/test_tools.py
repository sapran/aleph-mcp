import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx
from fastmcp import Client as MCPClient
from fastmcp import FastMCP

from aleph_mcp.config import Settings
from aleph_mcp.server import build_server

EXPECTED_TOOLS = {
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
}


@pytest.fixture
async def server(settings: Settings) -> AsyncIterator[FastMCP]:
    mcp, client = build_server(settings)
    try:
        yield mcp
    finally:
        await client.aclose()


async def test_tool_surface_is_exactly_the_read_set(server: FastMCP) -> None:
    async with MCPClient(server) as mcp:
        names = {t.name for t in await mcp.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_no_tool_advertises_a_mutation(server: FastMCP) -> None:
    forbidden = ("delete", "write", "create", "ingest", "upload", "flush", "reingest", "bulk")
    async with MCPClient(server) as mcp:
        names = {t.name for t in await mcp.list_tools()}
    assert not [n for n in names if any(word in n for word in forbidden)]


async def test_tool_names_carry_no_namespace_prefix(server: FastMCP) -> None:
    """The `aleph_` prefix the acordia `aleph-entity-graph` skill hardcodes is applied by
    whatever mounts this server. Adding one here would break every mount that already
    applies its own."""
    async with MCPClient(server) as mcp:
        names = {t.name for t in await mcp.list_tools()}
    assert not [n for n in names if n.startswith("aleph_")]
    # Guards the general case too: a prefix would leave every name sharing one leading
    # segment, which the bare read set does not.
    assert len({n.split("_", 1)[0] for n in names}) > 1


async def test_instructions_state_the_limits(server: FastMCP) -> None:
    async with MCPClient(server) as mcp:
        result = mcp.initialize_result
    text = result.instructions or ""
    assert "9999" in text
    assert "200" in text
    assert "no way to create, modify, ingest or delete" in text


async def test_list_collections_tool(server: FastMCP, respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [{"id": "42", "foreign_id": "case", "label": "Case files"}],
            },
        )
    )
    async with MCPClient(server) as mcp:
        result = await mcp.call_tool("list_collections", {})
    assert result.data["results"][0]["label"] == "Case files"


async def test_search_entities_tool(server: FastMCP, respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": {"value": 1},
                "results": [
                    {
                        "id": "e1",
                        "schema": "Person",
                        "caption": "Jane Doe",
                        "properties": {"name": ["Jane Doe"]},
                    }
                ],
                "facets": {"schema": {"values": [{"id": "Person", "count": 1}]}},
            },
        )
    )
    async with MCPClient(server) as mcp:
        result = await mcp.call_tool(
            "search_entities", {"q": "jane", "facets": ["schema"], "limit": 5}
        )
    assert result.data["results"][0]["caption"] == "Jane Doe"
    assert result.data["facets"]["schema"]["values"][0]["count"] == 1


async def test_deep_pagination_surfaces_as_tool_error(server: FastMCP) -> None:
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="9999"):
            await mcp.call_tool("search_entities", {"limit": 100, "offset": 9999})


async def test_http_error_surfaces_actionable_message(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1").mock(return_value=httpx.Response(403))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="WRITE/admin"):
            await mcp.call_tool("get_entity", {"entity_id": "e1"})


async def test_bad_entity_id_surfaces_as_tool_error(server: FastMCP) -> None:
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="invalid entity_id"):
            await mcp.call_tool("get_entity", {"entity_id": "../etc/passwd"})


# -- response-shape guarantees ------------------------------------------------
#
# These duplicate assertions that tests/test_client.py already makes against
# AlephClient, deliberately. The contract is published at the MCP layer: a refactor
# that registered a tool bypassing the slimming path would leave the client tests
# green while breaking every consumer.

BLOB_PROPS = ["bodyText", "bodyHtml", "safeHtml", "indexText", "translatedText"]


def _doc_entity(**extra: object) -> dict[str, object]:
    props: dict[str, object] = {"name": ["Memo"], "fileName": ["memo.pdf"]}
    props.update({p: [f"<{p} body>"] for p in BLOB_PROPS})
    return {"id": "d1", "schema": "Document", "properties": props, **extra}


async def test_search_hits_never_carry_document_text(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"total": 1, "results": [_doc_entity()]})
    )
    async with MCPClient(server) as mcp:
        hit = (await mcp.call_tool("search_entities", {"q": "memo"})).data["results"][0]
    assert not [p for p in BLOB_PROPS if p in hit["properties"]]
    assert hit["_omitted_properties"] == sorted(BLOB_PROPS)
    assert hit["properties"]["fileName"] == ["memo.pdf"]


async def test_get_entity_never_carries_document_text(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/d1").mock(return_value=httpx.Response(200, json=_doc_entity()))
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("get_entity", {"entity_id": "d1"})).data
    assert not [p for p in BLOB_PROPS if p in out["properties"]]
    assert out["_omitted_properties"] == sorted(BLOB_PROPS)


async def test_nothing_dropped_means_no_omitted_marker(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1").mock(
        return_value=httpx.Response(
            200, json={"id": "e1", "schema": "Person", "properties": {"name": ["Jane"]}}
        )
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("get_entity", {"entity_id": "e1"})).data
    assert "_omitted_properties" not in out


async def test_search_reports_the_scope_it_used(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"total": 0, "results": []})
    )
    async with MCPClient(server) as mcp:
        default = (await mcp.call_tool("search_entities", {"q": "x"})).data
        explicit = (await mcp.call_tool("search_entities", {"schema": "Ownership"})).data
    assert default["searched"] == {"schemata": "Thing"}
    assert explicit["searched"] == {"schema": "Ownership"}


async def test_unreachable_total_is_marked_unenumerated(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"total": {"value": 50_000}, "results": []})
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("search_entities", {"q": "x"})).data
    assert "UNENUMERATED" in out["_note"]


async def test_reachable_total_carries_no_note(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"total": {"value": 12}, "results": []})
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("search_entities", {"q": "x"})).data
    assert "_note" not in out


async def test_truncated_expansion_reports_true_degree(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1/expand").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "property": "ownershipOwner",
                        "count": 4137,
                        "entities": [{"id": "o1", "schema": "Ownership", "properties": {}}],
                    }
                ],
            },
        )
    )
    async with MCPClient(server) as mcp:
        group = (await mcp.call_tool("expand_entity", {"entity_id": "e1"})).data["results"][0]
    assert len(group["entities"]) == 1
    assert group["count"] == 4137


# -- refusal and error translation --------------------------------------------


async def test_deep_pagination_never_reaches_the_wire(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(return_value=httpx.Response(200, json={}))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="9999"):
            await mcp.call_tool("search_entities", {"limit": 100, "offset": 9999})
    assert route.call_count == 0


@pytest.mark.parametrize("args", [{"limit": -1}, {"offset": -1}])
async def test_negative_paging_surfaces_as_tool_error(
    server: FastMCP, respx_mock: respx.MockRouter, args: dict[str, int]
) -> None:
    route = respx_mock.get("/api/2/entities").mock(return_value=httpx.Response(200, json={}))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match=">= 0"):
            await mcp.call_tool("search_entities", args)
    assert route.call_count == 0


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ({"offset": -1}, "offset must be >= 0"),
        ({"limit": 0}, "between 1 and 200000"),
        ({"limit": 200_001}, "between 1 and 200000"),
    ],
)
async def test_text_slice_bounds_surface_as_tool_error(
    server: FastMCP, respx_mock: respx.MockRouter, args: dict[str, int], match: str
) -> None:
    route = respx_mock.get("/api/2/entities/d1").mock(return_value=httpx.Response(200, json={}))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match=match):
            await mcp.call_tool("get_entity_text", {"entity_id": "d1", **args})
    assert route.call_count == 0


@pytest.mark.parametrize("entity_id", ["e1\n", "e1\r", "e1\n\n", "e1 "])
async def test_trailing_whitespace_id_surfaces_as_tool_error(
    server: FastMCP, respx_mock: respx.MockRouter, entity_id: str
) -> None:
    """Regression: the validators used `$`, which matches before a trailing newline, so
    `"e1\\n"` reached httpx and surfaced its `InvalidURL` message instead of ours."""
    route = respx_mock.get(url__startswith="/api/2/entities").mock(
        return_value=httpx.Response(200, json={})
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="invalid entity_id"):
            await mcp.call_tool("get_entity", {"entity_id": entity_id})
    assert route.call_count == 0


@pytest.mark.parametrize("entity_id", ["..", ".", "...", "./."])
async def test_id_that_addresses_nothing_is_refused(
    server: FastMCP, respx_mock: respx.MockRouter, entity_id: str
) -> None:
    """`entityset_id=".."` used to normalise `/api/2/entitysets/../entities` down to
    `/api/2/entities` — an allowlisted read that answers a different question."""
    route = respx_mock.get(url__startswith="/api/2/entit").mock(
        return_value=httpx.Response(200, json={"total": 0, "results": []})
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="invalid entityset_id"):
            await mcp.call_tool("entityset_items", {"entityset_id": entity_id})
    assert route.call_count == 0


async def test_dotted_ids_are_still_accepted(server: FastMCP, respx_mock: respx.MockRouter) -> None:
    """The dot-only refusal must not become a ban on dots — real Aleph ids contain them."""
    respx_mock.get("/api/2/entities/a.b.c").mock(
        return_value=httpx.Response(200, json={"id": "a.b.c", "schema": "Person"})
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("get_entity", {"entity_id": "a.b.c"})).data
    assert out["id"] == "a.b.c"


async def test_numeric_collection_id_is_validated_before_interpolation(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(url__startswith="/api/2/collections").mock(
        return_value=httpx.Response(200, json={})
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="invalid collection_id"):
            await mcp.call_tool("get_collection", {"collection": "42\n"})
    assert route.call_count == 0


async def test_foreign_id_collection_lookup_still_accepts_free_form(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "42", "foreign_id": "my-case", "label": "Case"}]}
        )
    )
    respx_mock.get("/api/2/collections/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "42",
                "foreign_id": "my-case",
                "label": "Case",
                "statistics": {"schema": {"values": {"Person": 3}}},
            },
        )
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("get_collection", {"collection": "my-case"})).data
    assert out["foreign_id"] == "my-case"
    # Both branches of get_collection must answer with statistics, not just the numeric one.
    assert out["statistics"]["schema"]["values"]["Person"] == 3
    assert lookup.call_count == 1


# -- profiles ------------------------------------------------------------------


@pytest.mark.parametrize("profile_id", ["..", ".", "...", "./."])
async def test_profile_id_that_addresses_nothing_is_refused(
    server: FastMCP, respx_mock: respx.MockRouter, profile_id: str
) -> None:
    """Same normalisation hazard as entityset_items: `..` would walk the path up to a
    different, allowlisted read."""
    route = respx_mock.get(url__startswith="/api/2/profile").mock(
        return_value=httpx.Response(200, json={})
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="invalid profile_id"):
            await mcp.call_tool("get_profile", {"profile_id": profile_id})
    assert route.call_count == 0


async def test_get_profile_returns_the_merged_identity(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/profiles/p1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "p1",
                "type": "profile",
                "label": "Jane Doe",
                "entities": ["e1", "e2"],
                "merged": {"id": "p1", "schema": "Person", "properties": {"name": ["Jane Doe"]}},
            },
        )
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("get_profile", {"profile_id": "p1"})).data
    assert out["entities"] == ["e1", "e2"]
    assert out["merged"]["properties"]["name"] == ["Jane Doe"]


async def test_profile_tags_reaches_the_profile_route(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/profiles/p1/tags").mock(
        return_value=httpx.Response(200, json={"status": "ok", "total": 0, "results": []})
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("profile_tags", {"profile_id": "p1"})).data
    assert out["total"] == 0
    assert route.call_count == 1


async def test_profile_similar_reaches_the_profile_route(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/profiles/p1/similar").mock(
        return_value=httpx.Response(200, json={"total": 0, "results": []})
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("profile_similar", {"profile_id": "p1"})).data
    assert out["total"] == 0
    assert route.call_count == 1


async def test_expand_profile_refuses_a_limit_above_the_expand_cap(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(url__startswith="/api/2/profiles").mock(
        return_value=httpx.Response(200, json={})
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="200"):
            await mcp.call_tool("expand_profile", {"profile_id": "p1", "limit": 201})
    assert route.call_count == 0


async def test_get_entityset_returns_the_set_record(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entitysets/es1").mock(
        return_value=httpx.Response(200, json={"id": "es1", "type": "diagram", "label": "Network"})
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("get_entityset", {"entityset_id": "es1"})).data
    assert out["type"] == "diagram"
    assert out["label"] == "Network"


# -- pivots, lookup and cross-referencing --------------------------------------
#
# Five tools were registered but never invoked through MCP: a tool could have been
# wired to the wrong client method, or dropped its arguments, and every test stayed
# green. Each one below crosses the MCP boundary and asserts the payload a caller sees.


async def test_entity_tags_tool_returns_the_pivot_counts(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {"id": "mailto:j@x.test", "field": "emails", "value": "j@x.test", "count": 7}
                ],
            },
        )
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("entity_tags", {"entity_id": "e1"})).data
    tag = out["results"][0]
    assert (tag["field"], tag["count"]) == ("emails", 7)


async def test_similar_entities_tool_reports_score_and_judgement(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1/similar").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "score": 4.5,
                        "judgement": "positive",
                        "entity": _doc_entity(),
                    }
                ],
            },
        )
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("similar_entities", {"entity_id": "e1", "limit": 5})).data
    hit = out["results"][0]
    assert (hit["score"], hit["judgement"]) == (4.5, "positive")
    assert hit["entity"]["_omitted_properties"] == sorted(BLOB_PROPS)


async def test_match_entity_tool_posts_the_sample(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post("/api/2/match").mock(
        return_value=httpx.Response(
            200,
            json={"total": 1, "results": [{"id": "p1", "schema": "Person", "properties": {}}]},
        )
    )
    sample = {"schema": "Person", "properties": {"name": ["Jane Doe"]}}
    async with MCPClient(server) as mcp:
        out = (
            await mcp.call_tool(
                "match_entity", {"sample": sample, "collection_ids": ["42"], "limit": 3}
            )
        ).data
    assert out["results"][0]["id"] == "p1"
    request = route.calls.last.request
    assert json.loads(request.content) == sample
    assert ("collection_ids", "42") in parse_qsl(urlsplit(str(request.url)).query)


async def test_match_entity_tool_refuses_a_sample_without_a_schema(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """Aleph 400s a schema-less sample; refuse it here, with the shape to send instead."""
    route = respx_mock.post("/api/2/match").mock(return_value=httpx.Response(200, json={}))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="schema"):
            await mcp.call_tool("match_entity", {"sample": {"properties": {"name": ["Jane"]}}})
    assert route.call_count == 0


async def test_list_entitysets_tool_filters_by_set_type(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entitysets").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [{"id": "es1", "type": "diagram", "label": "Network"}],
            },
        )
    )
    async with MCPClient(server) as mcp:
        out = (
            await mcp.call_tool("list_entitysets", {"collection_id": "42", "set_type": "diagram"})
        ).data
    q = parse_qsl(urlsplit(str(route.calls.last.request.url)).query)
    assert ("filter:collection_id", "42") in q
    assert ("filter:type", "diagram") in q
    assert out["results"][0]["label"] == "Network"


async def test_entityset_items_tool_returns_slim_members(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entitysets/es1/entities").mock(
        return_value=httpx.Response(200, json={"total": 1, "results": [_doc_entity()]})
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("entityset_items", {"entityset_id": "es1"})).data
    assert out["results"][0]["_omitted_properties"] == sorted(BLOB_PROPS)


async def test_xref_results_tool_names_the_matched_collection(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/collections/42/xref").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "score": 3.25,
                        "judgement": "unsure",
                        "entity": {"id": "e1", "schema": "Person", "properties": {}},
                        "match": {"id": "m1", "schema": "Person", "properties": {}},
                        "match_collection_id": "77",
                    }
                ],
            },
        )
    )
    async with MCPClient(server) as mcp:
        out = (await mcp.call_tool("xref_results", {"collection_id": "42"})).data
    hit = out["results"][0]
    assert hit["match_collection_id"] == "77"
    assert (hit["entity"]["id"], hit["match"]["id"]) == ("e1", "m1")


async def test_xref_results_tool_rejects_a_foreign_id(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(url__startswith="/api/2/collections").mock(
        return_value=httpx.Response(200, json={})
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="numeric id"):
            await mcp.call_tool("xref_results", {"collection_id": "my-case"})
    assert route.call_count == 0


# -- coverage tripwire ---------------------------------------------------------

# Read at import: a blocking file read inside an async test is a lint error, and the
# file cannot change under us mid-run anyway.
TOOLS_CALLED_HERE = set(re.findall(r'call_tool\(\s*\n?\s*"(\w+)"', Path(__file__).read_text()))


async def test_every_registered_tool_is_exercised_through_mcp(server: FastMCP) -> None:
    """A tool can be registered against the wrong client method, or silently drop an
    argument, and no surface test notices. `test_tool_surface_is_exactly_the_read_set`
    only proves the name exists. This proves someone calls it.

    Adding a tool therefore means adding a test that calls it in this file — which is
    the point: the ceiling on coverage should be visible, not discovered later.
    """
    called = TOOLS_CALLED_HERE
    async with MCPClient(server) as mcp:
        registered = {t.name for t in await mcp.list_tools()}
    assert not registered - called, "registered but never called through MCP"
    assert not called - registered, "called but not registered"
