from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client as MCPClient
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from aleph_mcp.client import AlephClient
from aleph_mcp.config import Settings
from aleph_mcp.server import build_server
from tests.shapes import (
    BLOB_PROPS,
    assert_search_envelope,
    raw_document,
    raw_entity,
    raw_model,
    raw_search_payload,
    unfence,
)

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


# -- the MCP boundary ----------------------------------------------------------
#
# This file owns the MCP boundary and nothing else: that each tool forwards every
# argument to the right client method under the right name, returns that method's
# payload unmodified, and translates a client ValueError into a ToolError. Response
# shape and request building are AlephClient's contract and are asserted once, in
# tests/test_client.py. Two end-to-end cases below cross the whole stack on purpose,
# because a spy proves wiring but not that the stack composes.


def _recorder(
    name: str, recorded: dict[str, dict[str, Any]]
) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    async def recorder(_self: AlephClient, **kwargs: Any) -> dict[str, Any]:
        recorded[name] = kwargs
        return {"_spy": name}

    return recorder


@pytest.fixture
async def spied(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[FastMCP, dict[str, dict[str, Any]]]]:
    """A server whose client methods are recorders, patched before the client exists.

    Patching the class rather than the instance is what reaches the closures in
    server.py: build_server constructs AlephClient at call time, after this runs.
    """
    recorded: dict[str, dict[str, Any]] = {}
    for name in EXPECTED_TOOLS:
        monkeypatch.setattr(AlephClient, name, _recorder(name, recorded))
    mcp, client = build_server(settings)
    try:
        yield mcp, recorded
    finally:
        await client.aclose()


# Tool signatures use exactly the client's kwarg names, so one dict is both the call
# arguments and the expected forwarded kwargs. Every parameter of every tool appears
# here, with a value distinguishable from its default.
FORWARDING_CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("list_collections", {"q": "bank", "limit": 7}),
    ("get_collection", {"collection": "case-42"}),
    (
        "search_entities",
        {
            "collection": ["874", "42"],
            "q": "acme",
            "filters": {"countries": ["ru", "cy"]},
            "schema": "Person",
            "schemata": "LegalEntity",
            "facets": ["schema"],
            "facet_size": 5,
            "limit": 3,
            "offset": 2,
            "highlight": True,
        },
    ),
    ("get_entity", {"entity_id": "e1"}),
    ("expand_entity", {"entity_id": "e1", "properties": ["ownershipOwner"], "limit": 9}),
    ("entity_tags", {"entity_id": "e1"}),
    ("similar_entities", {"entity_id": "e1", "limit": 4}),
    (
        "match_entity",
        {
            "sample": {"schema": "Person", "properties": {"name": ["Jane Doe"]}},
            "collection": ["42"],
            "limit": 6,
        },
    ),
    ("get_profile", {"profile_id": "p1"}),
    ("profile_tags", {"profile_id": "p1"}),
    ("profile_similar", {"profile_id": "p1", "limit": 4}),
    ("expand_profile", {"profile_id": "p1", "properties": ["ownershipOwner"], "limit": 9}),
    ("list_entitysets", {"collection": "42", "set_type": "diagram", "limit": 8}),
    ("get_entityset", {"entityset_id": "es1"}),
    ("entityset_items", {"entityset_id": "es1", "limit": 11, "offset": 5}),
    ("xref_results", {"collection": "42", "limit": 12, "offset": 3}),
    ("get_entity_text", {"entity_id": "d1", "offset": 100, "limit": 500}),
)


def test_every_tool_has_a_forwarding_case() -> None:
    assert {name for name, _ in FORWARDING_CASES} == EXPECTED_TOOLS


@pytest.mark.parametrize(
    ("tool", "args"), FORWARDING_CASES, ids=[name for name, _ in FORWARDING_CASES]
)
async def test_tool_forwards_every_argument_and_returns_the_payload(
    spied: tuple[FastMCP, dict[str, dict[str, Any]]], tool: str, args: dict[str, Any]
) -> None:
    """A tool wired to the wrong client method, or dropping an argument, fails here.

    `recorded == {tool: args}` is exact on both sides: a renamed or dropped kwarg fails,
    and so does calling a second client method. The `_spy` sentinel proves the tool
    returns what the client returned — an empty dict could not tell that from nothing.
    """
    mcp_server, recorded = spied
    async with MCPClient(mcp_server) as mcp:
        result = await mcp.call_tool(tool, args)
    assert recorded == {tool: args}
    assert result.data == {"_spy": tool}


# Every refusal the client can raise, one per tool, with the phrase the caller is shown.
# Together these execute all seventeen `except ValueError: raise ToolError` arms.
#
# Each argument set must reach the client and fail *there*: a set that FastMCP rejects on
# the signature never enters the try block, so the arm this file exists to cover goes
# unexecuted while the test still passes on the phrase. That is why every collection-taking
# tool below is given a `collection` — and a numeric-looking one, so the refusal is the
# client's own and costs no lookup request.
ERROR_CASES: tuple[tuple[str, dict[str, Any], str, int], ...] = (
    ("list_collections", {"limit": 101}, "between 0 and 100", 0),
    ("get_collection", {"collection": "unknown-fid"}, "no collection with foreign_id", 1),
    (
        "search_entities",
        {"collection": "874", "limit": 100, "offset": 9999},
        "cannot page past result 9999",
        0,
    ),
    ("get_entity", {"entity_id": "../etc/passwd"}, "invalid entity_id", 0),
    ("expand_entity", {"entity_id": "e1", "limit": 201}, "200", 0),
    ("entity_tags", {"entity_id": "e1\n"}, "invalid entity_id", 0),
    ("similar_entities", {"entity_id": ".."}, "invalid entity_id", 0),
    (
        "match_entity",
        {"sample": {"properties": {"name": ["x"]}}, "collection": "874"},
        "must include a followthemoney 'schema' key",
        0,
    ),
    ("get_profile", {"profile_id": ".."}, "invalid profile_id", 0),
    ("profile_tags", {"profile_id": "p 1"}, "invalid profile_id", 0),
    ("profile_similar", {"profile_id": ".."}, "invalid profile_id", 0),
    ("expand_profile", {"profile_id": "p1", "limit": 201}, "200", 0),
    ("list_entitysets", {"collection": "42\n"}, "expected a numeric collection id", 0),
    ("get_entityset", {"entityset_id": ".."}, "invalid entityset_id", 0),
    ("entityset_items", {"entityset_id": "es1", "limit": 201}, "between 0 and 200", 0),
    ("xref_results", {"collection": "42\n"}, "expected a numeric collection id", 0),
    ("get_entity_text", {"entity_id": "d1", "limit": 200001}, "200000", 0),
)


def test_every_tool_has_a_refusal_case() -> None:
    assert {name for name, *_ in ERROR_CASES} == EXPECTED_TOOLS


@pytest.mark.parametrize(
    ("tool", "args", "match", "wire_calls"),
    ERROR_CASES,
    ids=[case[0] for case in ERROR_CASES],
)
async def test_client_refusal_surfaces_as_a_tool_error(
    server: FastMCP,
    respx_mock: respx.MockRouter,
    tool: str,
    args: dict[str, Any],
    match: str,
    wire_calls: int,
) -> None:
    """The refusal reaches the caller as a ToolError carrying the client's own message,
    and nothing is sent to Aleph — a refused call must cost no request."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    async with MCPClient(server) as mcp:
        with pytest.raises(ToolError, match=match) as excinfo:
            await mcp.call_tool(tool, args)
    # The arm under test is the client's own `except ValueError`, so the refusal has to
    # come from the client rather than from FastMCP's signature validation: an argument
    # set the signature rejects never enters the try block at all, and the message it
    # raises instead quotes the whole input dict — which can satisfy the expected phrase
    # by accident. Measured: with `collection` missing, the search_entities case below
    # passed on the 9999 echoed back inside that quoted input.
    assert "validation error" not in str(excinfo.value)
    assert wire.call_count == wire_calls
    if wire_calls:
        # get_collection can only learn a foreign_id is unknown by asking the listing;
        # the detail route must still never be reached.
        assert [call.request.url.path for call in wire.calls] == ["/api/2/collections"]


# -- end to end ----------------------------------------------------------------


async def test_search_entities_end_to_end(server: FastMCP, respx_mock: respx.MockRouter) -> None:
    """The whole stack against a real-shaped payload: MCP tool, client, slimmer."""
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=raw_model()))
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json=raw_search_payload(
                raw_entity(),
                raw_document(),
                total=3,
                facets={"schema": {"values": [{"id": "Person", "count": 2}]}},
            ),
        )
    )
    async with MCPClient(server) as mcp:
        result = await mcp.call_tool(
            "search_entities",
            {
                "collection": "874",
                "q": "acme",
                "facets": ["schema"],
                "highlight": True,
                "limit": 2,
            },
        )
    out = result.data
    assert_search_envelope(out, searched={"schemata": "Thing", "collection": ["874"]})
    assert out["results"][1]["_omitted_properties"] == sorted(BLOB_PROPS)
    assert out["facets"]["schema"]["values"][0]["count"] == 2
    assert "_note" not in out


async def test_get_entity_text_end_to_end(server: FastMCP, respx_mock: respx.MockRouter) -> None:
    """A real text slice across MCP: the page-child fallback, bounded and marked truncated."""
    respx_mock.get("/api/2/entities/d1").mock(
        return_value=httpx.Response(
            200, json=raw_entity(id="d1", schema="Pages", properties={"fileName": ["scan.pdf"]})
        )
    )
    pages = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json=raw_search_payload(
                raw_entity(id="p1", schema="Page", properties={"bodyText": ["page one text"]}),
                raw_entity(id="p2", schema="Page", properties={"bodyText": ["page two text"]}),
                total=2,
            ),
        )
    )
    async with MCPClient(server) as mcp:
        result = await mcp.call_tool(
            "get_entity_text", {"entity_id": "d1", "offset": 0, "limit": 10}
        )
    out = result.data
    joined = "page one text\n\npage two text"
    assert pages.call_count == 1
    assert out["source"] == "pages"
    assert unfence(out["text"]) == joined[:10]
    assert out["returned_chars"] == 10
    assert out["total_chars"] == len(joined)
    assert out["truncated"] is True
