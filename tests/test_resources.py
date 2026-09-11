import json
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client as MCPClient
from fastmcp import FastMCP

from aleph_mcp.client import MAX_SCHEMA_LIST_CHARS, MAX_SCHEMA_NAMES
from aleph_mcp.config import Settings
from aleph_mcp.echo import SCHEMA_NAME
from aleph_mcp.server import build_server
from tests.shapes import raw_model
from tests.test_client import HOSTILE_SCHEMA_NAME


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
    # The `origin` sentence is the half that actually tells the model these names are the
    # instance's and not this server's vocabulary; `trust` alone could keep its value while
    # that sentence was deleted.
    assert "Aleph instance" in out["_provenance"]["origin"]
    assert "_omitted_schemata" not in out, "five names is under the cap; nothing was dropped"


async def test_schemata_resource_neutralises_hostile_names_in_every_list(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """The listing is the other half of why `SCHEMA_NAME` exists, and unlike the refusal it
    has no `repr` at its call site -- these names are JSON string values the model reads
    directly. Length alone does not cover it: swapping `render` for a plain 64-character
    truncation keeps every length assertion green while shipping raw ESC, NUL and U+202E.

    All three lists, because `matchable` and `edges` are separate copies of the same name.
    """
    model = {
        "model": {
            "schemata": {
                HOSTILE_SCHEMA_NAME: {
                    "matchable": True,
                    "edge": {"source": "owner", "target": "asset"},
                }
            }
        }
    }
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=model))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    for key in ("all", "matchable", "edges"):
        (served,) = out[key]
        assert all(ch.isprintable() for ch in served), f"{key}: unprintable survived {served!r}"
        assert "\x1b" not in served and "\x00" not in served and "‮" not in served
        assert "�" in served, f"{key}: the substitution must be visible as damage"


@pytest.mark.parametrize(
    ("declared", "expect_omission"),
    [(500, False), (501, True)],
    ids=["exactly-at-the-cap", "one-over"],
)
async def test_schemata_resource_at_the_count_boundary(
    server: FastMCP, respx_mock: respx.MockRouter, declared: int, expect_omission: bool
) -> None:
    """`>` against `>=` is a one-character mutation that survived the whole suite, and its
    failure mode is the worse direction: at exactly the cap the resource would announce a cut
    that did not happen, and `_omitted_schemata` is the one key a caller is meant to trust."""
    model = {"model": {"schemata": {f"S{i:05d}": {} for i in range(declared)}}}
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=model))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    assert out["count"] == declared
    assert len(out["all"]) == min(declared, 500)
    assert ("_omitted_schemata" in out) is expect_omission


async def test_schemata_resource_bounds_the_joined_length_not_just_the_count(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """A count cap beside a per-name cap is a ceiling of count x cap, not a bound -- the same
    reasoning `_suggestion_clause` applies to the refusal. Without the character budget, 500
    names at the 64-character cap is ~32,500 characters per list and ~97,000 across three."""
    long_names = {f"S{i:03d}" + "x" * 80: {"matchable": True} for i in range(500)}
    respx_mock.get("/api/2/metadata").mock(
        return_value=httpx.Response(200, json={"model": {"schemata": long_names}})
    )
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    assert MAX_SCHEMA_LIST_CHARS == 8000
    assert sum(len(n) for n in out["all"]) <= 8000
    assert len(out["all"]) < 500, "the character budget must bite before the count cap"
    assert out["_omitted_schemata"]["all"] == 500 - len(out["all"])
    assert out["count"] == 500, "count is still the instance's own total"


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
    # Every name is both matchable and an edge, so all three lists clip and all three must
    # say so: `edges` is the subset the docstring calls "a shorter but equally unbounded
    # path", and it was the one list no fixture exercised.
    model = {
        "model": {
            "schemata": {
                f"S{i:05d}": {"matchable": True, "edge": {"source": "owner", "target": "asset"}}
                for i in range(507)
            }
        }
    }
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=model))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schemata"))
    assert MAX_SCHEMA_NAMES == 500
    assert out["count"] == 507, "count is the instance's own total, not the length served"
    assert len(out["all"]) == 500
    assert out["_omitted_schemata"] == {"matchable": 7, "edges": 7, "all": 7}


async def test_schema_resource_exposes_edge_and_range(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=raw_model()))
    async with MCPClient(server) as mcp:
        out = _payload(await mcp.read_resource("aleph://schema/Ownership"))
    assert out["edge"]["source"] == "owner"
    assert out["properties"]["owner"]["range"] == "LegalEntity"


async def test_hostile_schema_refusal_is_neutralised_through_the_shipped_path(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """The refusal tests in `test_client.py` call `get_schema` directly, which skips
    `_as_resource_error`, FastMCP's error handling and the serialisation the model actually
    sees. Their own docstrings reason about this path -- "leaves through `aleph://schema/{name}`
    unprefixed, which is the shape that survives `mask_error_details`" -- so it is the path
    that has to be checked, not the inner call.
    """
    model = {"model": {"schemata": {HOSTILE_SCHEMA_NAME: {}}}}
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=model))
    async with MCPClient(server) as mcp:
        with pytest.raises(Exception, match="unknown followthemoney schema") as excinfo:
            await mcp.read_resource("aleph://schema/Persson")
    message = str(excinfo.value)
    assert all(ch.isprintable() for ch in message), f"unprintable reached the model: {message!r}"
    assert "\x1b" not in message and "\x00" not in message and "‮" not in message
    assert not message.startswith("Error reading resource"), (
        "the refusal must stay unprefixed -- a prefixed message is masked away entirely"
    )


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
