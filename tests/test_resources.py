import json
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client as MCPClient
from fastmcp import FastMCP

from aleph_mcp.client import MAX_SCHEMA_NAMES
from aleph_mcp.config import Settings
from aleph_mcp.echo import SCHEMA_NAME
from aleph_mcp.server import build_server
from tests.shapes import raw_model


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
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=raw_model()))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    assert out["count"] == 4
    assert out["matchable"] == ["Person"]
    assert out["edges"] == ["Ownership"]


async def test_schemata_resource_bounds_and_labels_upstream_names(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """Every name here is upstream text, and the model has no other way to know that.

    Before this bound the resource returned `sorted(schemata)` -- every key, unbounded in
    count and in length, held back only by the 25 MiB response ceiling -- and carried no
    provenance label, so the names read as this server's own vocabulary.
    """
    model = raw_model()
    model["model"]["schemata"]["Pers" + "o" * 20_000] = {"matchable": True}
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=model))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    assert max(len(n) for n in out["all"]) <= SCHEMA_NAME.max_chars + 1
    assert max(len(n) for n in out["matchable"]) <= SCHEMA_NAME.max_chars + 1
    assert out["_provenance"]["trust"] == "untrusted"
    assert "_omitted_schemata" not in out, "five names is under the cap; nothing was dropped"


async def test_schemata_resource_reports_what_it_dropped(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """A confidently incomplete answer is a defect in this server, so a cut list says so --
    and `count` keeps naming the instance's own total rather than the length served.

    The numbers are written out rather than derived from `MAX_SCHEMA_NAMES`, for the reason
    `tests/test_echo.py` gives about the policy caps: an expectation computed from the
    constant it guards moves with it, so widening the bound would leave this green while the
    echo it bounds grew. Pinned here, raising the cap goes red and has to be chosen again.
    """
    model = {"model": {"schemata": {f"S{i:05d}": {"matchable": True} for i in range(507)}}}
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=model))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    assert MAX_SCHEMA_NAMES == 500
    assert out["count"] == 507, "count is the instance's own total, not the length served"
    assert len(out["all"]) == 500
    assert out["_omitted_schemata"] == {"all": 7, "matchable": 7}


async def test_schema_resource_exposes_edge_and_range(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=raw_model()))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schema/Ownership"))
    assert out["edge"]["source"] == "owner"
    assert out["properties"]["owner"]["range"] == "LegalEntity"


async def test_unknown_schema_resource_errors(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=raw_model()))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="unknown followthemoney schema") as excinfo:
            await mcp.read_resource("aleph://schema/Nonsense")
    # The client's own message reaches the caller unprefixed, which is what the refusal
    # seam is for. The phrase alone cannot see that: FastMCP turns a ResourceError into a
    # protocol McpError either way, and an untranslated refusal arrives as the same
    # McpError with the same phrase appended to "Error reading resource '<uri>': ".
    assert not str(excinfo.value).startswith("Error reading resource")


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
