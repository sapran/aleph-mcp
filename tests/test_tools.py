from collections.abc import AsyncIterator

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
    "list_entitysets",
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
