import inspect
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import fastmcp
import httpx
import pytest
import respx
from fastmcp import Client as MCPClient
from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError

from aleph_mcp.client import AlephClient, _Ent
from aleph_mcp.config import Settings
from aleph_mcp.errors import Refusal
from aleph_mcp.server import _as_resource_error, _as_tool_error, build_server
from tests.conftest import assert_model_not_fetched
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
# Together these prove the refusal seam is applied to all seventeen tools.
#
# Each argument set must reach the client and fail *there*: a set that FastMCP rejects on
# the signature never reaches the seam at all, so the translation this file exists to cover
# goes unexecuted while the test still passes on the phrase. That is why every
# collection-taking tool below is given a `collection` — and a numeric-looking one, so the
# refusal is the client's own and costs no lookup request.
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
    # What the seam translates is the client's own `except ValueError`, so the refusal has
    # to come from the client rather than from FastMCP's signature validation: an argument
    # set the signature rejects never reaches the seam at all, and the message it
    # raises instead quotes the whole input dict — which can satisfy the expected phrase
    # by accident. Measured: with `collection` missing, the search_entities case below
    # passed on the 9999 echoed back inside that quoted input.
    assert "validation error" not in str(excinfo.value)
    # The client's own message reaches the caller unprefixed, which is the whole job of
    # the refusal seam. `match` alone cannot see that job being done: with the seam
    # bypassed the refusal still arrives as a ToolError carrying the same phrase, because
    # FastMCP appends it to "Error calling tool '<name>': " and mask_error_details is off.
    # Measured on main @ 1952232: deleting all eighteen arms changed no test outcome.
    #
    # This assertion fails open — it is pinned to a FastMCP string literal that is not
    # public API, so a reword upstream makes it vacuously true and silently unpins the
    # seam again. test_a_refusal_survives_error_masking below is the fail-closed backstop;
    # keep both.
    assert not str(excinfo.value).startswith("Error calling tool")
    assert wire.call_count == wire_calls
    assert_model_not_fetched(respx_mock)
    if wire_calls:
        # get_collection can only learn a foreign_id is unknown by asking the listing;
        # the detail route must still never be reached.
        assert [call.request.url.path for call in wire.calls] == ["/api/2/collections"]


@pytest.fixture
async def masked_server(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FastMCP]:
    """A server built with FastMCP's error masking on.

    FastMCP reads `mask_error_details` when the server is constructed, not when a tool is
    called, so this has to be set before build_server rather than inside the test.
    """
    monkeypatch.setattr(fastmcp.settings, "mask_error_details", True)
    mcp, client = build_server(settings)
    try:
        yield mcp
    finally:
        await client.aclose()


async def test_the_masked_session_is_actually_masking(
    masked_server: FastMCP, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control for every masking test below, and the one they cannot be.

    Each of those asserts that a refusal's own words survive masking. All of them also pass
    when masking never happens at all, because an unmasked message contains its own words
    too -- so the whole group degenerates the moment `mask_error_details` stops taking
    effect. The fixture's `monkeypatch.setattr` catches the setting being *renamed*; it
    cannot catch it being deprecated to a no-op. Measured: setting the fixture to `False`
    and simultaneously reverting `_shape` to `RuntimeError` -- the exact defect those tests
    exist to catch -- left all 18 of them green.

    This one fails in that world instead of passing. A non-refusal raised inside a tool must
    have its message replaced, so the sentinel can only arrive if masking is off.
    """
    sentinel = "SENTINEL-8c4f1a2e-masking-is-off"

    @masked_server.tool
    async def masking_probe() -> dict[str, Any]:
        """A fault, not a refusal: FastMCP replaces its message when masking is on."""
        raise RuntimeError(sentinel)

    async with MCPClient(masked_server) as mcp:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool("masking_probe", {})

    assert sentinel not in str(excinfo.value), (
        "the masked session let a non-refusal's own message through, so masking is not in "
        "effect and every masking test in this file is passing vacuously"
    )


@pytest.mark.parametrize(
    ("tool", "args", "match"),
    [(name, args, match) for name, args, match, _ in ERROR_CASES],
    ids=[case[0] for case in ERROR_CASES],
)
async def test_a_refusal_survives_error_masking(
    masked_server: FastMCP,
    respx_mock: respx.MockRouter,
    tool: str,
    args: dict[str, Any],
    match: str,
) -> None:
    """The fail-closed backstop for the unprefixed-message assertion above.

    That one is pinned to a FastMCP string literal, so an upstream reword would leave it
    vacuously true and the seam unpinned. Masking removes the prefix question entirely:
    FastMCP replaces the whole message with `Error calling tool '<name>'`, so the client's
    own phrase can only arrive if the seam put it there. Any rewording still strips the
    message, so this keeps discriminating.
    """
    respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    async with MCPClient(masked_server) as mcp:
        with pytest.raises(ToolError, match=match):
            await mcp.call_tool(tool, args)


# -- the one refusal that is not a client ValueError ---------------------------
#
# The shaping seam in client.py refuses a reply carrying a raw upstream entity. It is a
# refusal like any other on this surface and has to clear the same two bars, but it reaches
# the caller by a different route: it is raised at the seam rather than translated from a
# ValueError by the adapter above, so neither table covers it. Measured before it was
# raised as a ToolError: it arrived as `Error calling tool 'get_profile': ...` unmasked, and
# with masking on, the whole message -- including the sentence telling the caller that
# retrying cannot help -- was replaced by `Error calling tool 'get_profile'`.


def _profile_with_a_raw_entity() -> dict[str, Any]:
    """A profile whose `entities` holds an object rather than an id string.

    The one payload that reaches the seam's guard through a real tool call: get_profile
    copies `entities` through raw, so an entity there is never marked and never shaped.
    """
    return {"id": "p1", "entities": [raw_document()], "merged": raw_entity(id="e1")}


async def test_the_shaping_refusal_reaches_the_caller_unprefixed(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """The seam's own refusal clears the bar every other refusal on this surface clears.

    `Error calling tool '<name>': ` is what FastMCP prepends to an exception it does not
    recognise as a refusal, and the seventeen rows above assert no refusal carries it.
    """
    respx_mock.get("/api/2/profiles/p1").mock(
        return_value=httpx.Response(200, json=_profile_with_a_raw_entity())
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(ToolError, match="get_profile cannot answer") as excinfo:
            await mcp.call_tool("get_profile", {"profile_id": "p1"})
    assert not str(excinfo.value).startswith("Error calling tool")
    # The offending keys are upstream's to choose, so none of them may be quoted back.
    assert "bodyText" not in str(excinfo.value)


async def test_the_shaping_refusal_survives_error_masking(
    masked_server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """The fail-closed backstop, and the half that matters most here.

    Masking replaces the whole message of anything that is not a ToolError, so the sentence
    telling the caller that nothing about the call can change this outcome is exactly the
    text that disappeared. It is also the text that most needs to survive: this refusal is
    the one a caller can never clear by retrying or by changing its arguments.
    """
    respx_mock.get("/api/2/profiles/p1").mock(
        return_value=httpx.Response(200, json=_profile_with_a_raw_entity())
    )
    async with MCPClient(masked_server) as mcp:
        with pytest.raises(ToolError, match="get_profile cannot answer") as excinfo:
            await mcp.call_tool("get_profile", {"profile_id": "p1"})
    assert "retrying will not help" in str(excinfo.value)


@pytest.mark.parametrize("masked", [False, True], ids=["unmasked", "masked"])
async def test_a_marker_that_missed_the_seam_refuses_actionably(
    settings: Settings, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, masked: bool
) -> None:
    """A marker reaching the boundary is a permanent server defect, and must say so.

    The markers already refuse to serialise, so nothing leaks either way -- but that refusal
    is raised inside pydantic, which wraps it in `PydanticSerializationError`, and FastMCP
    sees only the wrapper. Measured before the seam checked for markers, with
    `_MarkerEscaped` already made a ToolError:

        masked=False -> Error calling tool 'get_entity': Error serializing to JSON: ...
        masked=True  -> Error calling tool 'get_entity'

    Prefixed, erased under masking, and reading as a transient hiccup -- so a model retries
    an endpoint that can never work, paying the upstream request every time, because the
    endpoint's own fetch completes before the seam. The refusal has to be phrased where the
    reply is still ours, which is the adapter in server.py.

    The client method is unhooked here rather than a probe tool being built by hand, because
    forgetting `@_shaped` on a new endpoint is the mistake this guards, and going through
    `build_server` is what proves the adapter and not the serialiser produced the answer.
    """
    monkeypatch.setattr(fastmcp.settings, "mask_error_details", masked)
    monkeypatch.setattr(AlephClient, "get_entity", AlephClient.get_entity.__wrapped__, raising=True)
    mcp, client = build_server(settings)
    respx_mock.get("/api/2/entities/d1").mock(return_value=httpx.Response(200, json=raw_document()))
    try:
        async with MCPClient(mcp) as session:
            with pytest.raises(ToolError) as excinfo:
                await session.call_tool("get_entity", {"entity_id": "d1"})
    finally:
        await client.aclose()

    message = str(excinfo.value)
    assert not message.startswith("Error calling tool"), message
    assert "retrying will not help" in message, message
    for prop in BLOB_PROPS:
        assert f"<{prop} body>" not in message


async def test_a_marker_that_missed_the_seam_cannot_reach_the_caller() -> None:
    """The inverse mistake, measured at the boundary that decides whether it matters.

    `_shape` refuses a raw dict left in a reply. The other direction -- a marker that never
    reached `_shape`, because the method building it was never hooked to the seam -- was
    fail-open: measured through this same boundary, it returned `isError: False` carrying
    the entire document body. The tool here is built by hand rather than by unhooking a real
    one, so the check keeps working whatever the client's method set becomes; the reply is
    shaped exactly the way `_slim_result` shapes one, which is what an author writing the
    next endpoint copies.
    """
    probe = FastMCP("marker-probe")

    @probe.tool
    async def forgot_to_shape() -> dict[str, Any]:
        """A reply built with markers by a method that never went through the seam."""
        return {"merged": _Ent(raw_document())}

    async with MCPClient(probe) as mcp:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool("forgot_to_shape", {})

    message = str(excinfo.value)
    assert "shaping seam" in message
    for prop in BLOB_PROPS:
        assert f"<{prop} body>" not in message


# -- the seam itself -----------------------------------------------------------
#
# Every tool and the schema resource now share one translation, and the tests above can
# only see it through FastMCP, which rewrites what they observe. These reach it directly,
# so the message can be pinned exactly rather than by phrase.


@pytest.mark.parametrize(
    ("translate", "expected"),
    [(_as_tool_error, ToolError), (_as_resource_error, ResourceError)],
    ids=["tool", "resource"],
)
async def test_the_seam_forwards_the_message_and_keeps_the_cause(
    translate: Callable[..., Any], expected: type[Exception]
) -> None:
    """The caller is shown the client's message and nothing added to it."""

    @translate
    async def refuses() -> dict[str, Any]:
        raise Refusal("limit must be between 0 and 100")

    with pytest.raises(expected) as excinfo:
        await refuses()
    assert str(excinfo.value) == "limit must be between 0 and 100"
    assert isinstance(excinfo.value.__cause__, Refusal)


@pytest.mark.parametrize(
    "defect",
    [
        RuntimeError("upstream fell over"),
        ValueError("invalid literal for int() with base 10: 'not-a-number'"),
        json.JSONDecodeError("Expecting value", "<html>", 0),
        UnicodeDecodeError("utf-8", b"\x89PNG", 0, 1, "invalid start byte"),
    ],
    ids=["runtime-error", "in-body-int", "nested-json-loads", "non-utf8-decode"],
)
async def test_the_seam_leaves_a_non_refusal_alone(defect: Exception) -> None:
    """A `Refusal` is the client saying no. Anything else is a fault, and dressing it up
    as a refusal would tell the model to fix its arguments and retry against a broken
    upstream.

    Three of these four are `ValueError` subclasses, and that is the point. The seam used
    to select on `ValueError`, which Python hands out for argument validation, for `int()`,
    for `json.loads` and for `bytes.decode` alike -- so it could not tell a refusal this
    server chose to make from any of them. Measured on `develop @ 7f9c139`: a tool body
    calling `int()` on upstream text reached the caller as `invalid literal for int() with
    base 10: 'not-a-number'`, unprefixed and surviving `mask_error_details`, which is the
    shape reserved for a deliberate refusal.

    It matters more than it looks: the translation wraps the whole function body, where the
    arms it replaced wrapped only the `await client.X(...)` call.
    """

    @_as_tool_error
    async def breaks() -> dict[str, Any]:
        raise defect

    with pytest.raises(type(defect)) as excinfo:
        await breaks()
    assert excinfo.value is defect, "the seam must not re-raise it as something else"


def test_the_seam_carries_what_fastmcp_reads() -> None:
    """Gate A in miniature. FastMCP builds a tool's description from __doc__ and its input
    schema from the signature, so a wrapper that dropped either would change the product
    while every behavioural test here stayed green."""

    async def tool_fn(entity_id: str, limit: int = 20) -> dict[str, Any]:
        """Fetch one entity by id, with its properties and caption."""
        return {}

    wrapped = _as_tool_error(tool_fn)
    assert wrapped.__doc__ == "Fetch one entity by id, with its properties and caption."
    assert wrapped.__name__ == "tool_fn"
    assert inspect.signature(wrapped) == inspect.signature(tool_fn)


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


async def test_a_maintenance_page_on_200_is_not_answered_as_a_bad_argument(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """The measurement from the implementation-notes entry, re-run through the shipped path.

    Everything above reaches the seam directly, which is the only way to pin a message
    exactly -- but the defect was reported as what a *model* receives, and FastMCP rewrites
    that. So this one goes through `MCPClient`: an instance answering `200` with an HTML
    maintenance page used to produce `Expecting value: line 1 column 1 (char 0)` here,
    which is a sentence about the caller's JSON, not about the instance being down.
    """
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            content=b"<!DOCTYPE html><html><body><h1>Scheduled maintenance</h1></body></html>",
            headers={"content-type": "text/html"},
        )
    )
    async with MCPClient(server) as mcp:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool("list_collections", {})
    message = str(excinfo.value)
    assert message.startswith("list_collections:"), (
        f"the refusal must name the tool the caller called: {message!r}"
    )
    assert not message.startswith("Expecting value"), "the decoder's bare string is not an answer"
    assert "not JSON" in message and "upstream" in message, message
    assert "Scheduled maintenance" not in message, "the body is never quoted"
    # The decoder text is still worth having -- "Expecting value: line 1 column 1" and
    # "Unterminated string starting at: line 1 column 13" separate a page that is not JSON
    # at all from a body cut mid-transfer -- but only behind the label, never as the whole
    # message.
    assert "untrusted transport text" in message, message
