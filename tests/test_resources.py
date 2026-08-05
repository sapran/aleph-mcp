import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from fastmcp import Client as MCPClient
from fastmcp import FastMCP

from aleph_mcp.config import Settings
from aleph_mcp.server import build_server

_MODEL = {
    "model": {
        "schemata": {
            "Person": {
                "label": "Person",
                "matchable": True,
                "schemata": ["Person", "LegalEntity", "Thing"],
                "extends": ["LegalEntity"],
                "caption": ["name"],
                "properties": {"name": {"label": "Name", "type": "name"}},
            },
            "Ownership": {
                "label": "Ownership",
                "edge": {"source": "owner", "target": "asset", "directed": True},
                "properties": {
                    "owner": {"label": "Owner", "type": "entity", "range": "LegalEntity"}
                },
            },
        }
    }
}


@pytest.fixture
async def server(settings: Settings) -> AsyncIterator[FastMCP]:
    mcp, client = build_server(settings)
    try:
        yield mcp
    finally:
        await client.aclose()


def _payload(result: list) -> dict:
    return json.loads(result[0].text)


async def test_resource_surface_is_exactly_the_read_set(server: FastMCP) -> None:
    async with MCPClient(server) as mcp:
        static = {str(r.uri): r.mimeType for r in await mcp.list_resources()}
        templates = {t.uriTemplate: t.mimeType for t in await mcp.list_resource_templates()}
    assert set(static) == {"aleph://collections", "aleph://schemata"}
    assert set(templates) == {"aleph://schema/{name}"}
    assert set(static.values()) | set(templates.values()) == {"application/json"}


async def test_collections_resource(server: FastMCP, respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"total": 1, "results": [{"id": "42"}]})
    )
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://collections"))
    assert out["results"][0]["id"] == "42"


async def test_schemata_resource_splits_matchable_and_edges(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=_MODEL))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    assert out["count"] == 2
    assert out["matchable"] == ["Person"]
    assert out["edges"] == ["Ownership"]


async def test_schema_resource_exposes_edge_and_range(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=_MODEL))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schema/Ownership"))
    assert out["edge"]["source"] == "owner"
    assert out["properties"]["owner"]["range"] == "LegalEntity"


async def test_unknown_schema_resource_errors(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=_MODEL))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="unknown followthemoney schema"):
            await mcp.read_resource("aleph://schema/Nonsense")
