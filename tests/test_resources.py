import json
import re
from collections.abc import AsyncIterator
from pathlib import Path

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


# -- coverage tripwire ---------------------------------------------------------

# Read at import: a blocking file read inside an async test is a lint error.
URIS_READ_HERE = set(re.findall(r'read_resource\("([^"{}]+)"\)', Path(__file__).read_text()))


async def test_every_registered_resource_is_read_here(server: FastMCP) -> None:
    """Templates are matched by the concrete uri a test actually reads, so a template
    whose only proof is that it appears in list_resource_templates fails this."""
    async with MCPClient(server) as mcp:
        static = {str(r.uri) for r in await mcp.list_resources()}
        templates = [t.uriTemplate for t in await mcp.list_resource_templates()]

    assert not static - URIS_READ_HERE, "registered but never read"
    for template in templates:
        prefix = template.split("{", 1)[0]
        assert any(uri.startswith(prefix) for uri in URIS_READ_HERE), f"{template} never read"
