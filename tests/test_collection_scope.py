"""The collection-scope contract: a search has to name the collection it searched.

Aleph answers an unscoped search *successfully*, so a query that meant one collection and
did not say so comes back full of another collection's rows — ranked, plausible, and with
no error anywhere. That is the whole reason the scope is required rather than defaulted,
that `"*"` is the only way to opt out of it and says so in the reply, and that a second
spelling of it in `filters` is refused rather than merged.

Each case below is pinned at the layer that makes the decision. The two refusals FastMCP
owns — a missing argument, and what the tool schemas advertise — go through `MCPClient`,
because a check against the Python signature would pass while the model was shown
something else. Request building, resolution, caching and the reported scope are
`AlephClient`'s contract and are asserted against the wire.
"""

from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx
from fastmcp import Client as MCPClient
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from aleph_mcp.client import ALL_COLLECTIONS, MAX_PAGE, AlephClient
from aleph_mcp.config import Settings
from aleph_mcp.server import build_server
from tests.shapes import raw_entity, raw_model, raw_search_payload

# The spellings this change exists to remove. `collection` is the one name for the scope
# across the whole surface, so neither of these may reappear on any tool.
FORBIDDEN_SCOPE_ARGS = frozenset({"collection_id", "collection_ids"})


def _query(request: httpx.Request) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(str(request.url)).query, keep_blank_values=True)


def _scopes(request: httpx.Request) -> list[str]:
    """Every `filter:collection_id` value sent, in order — a list ORs within the key."""
    return [value for key, value in _query(request) if key == "filter:collection_id"]


@pytest.fixture
async def server(settings: Settings) -> AsyncIterator[FastMCP]:
    mcp, client = build_server(settings)
    try:
        yield mcp
    finally:
        await client.aclose()


# -- the scope is required -----------------------------------------------------


async def test_a_search_with_no_collection_is_refused_before_any_request(
    server: FastMCP, respx_mock: respx.MockRouter
) -> None:
    """Driven through `MCPClient` on purpose: the refusal must come from the tool
    signature, ahead of any code in this repo. Any default at all — `None`, `"*"`, the
    last collection seen — is exactly the silent substitution this argument exists to
    prevent, and a client-level test could not tell a default apart from a refusal."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    async with MCPClient(server) as mcp:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool("search_entities", {"q": "acme"})
    message = str(excinfo.value)
    assert "collection" in message, f"the refusal must name the missing argument: {message}"
    assert "Missing required argument" in message, message
    assert wire.call_count == 0, "an unscoped call must cost no request"


async def test_a_numeric_collection_emits_one_filter_and_is_reported(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """A numeric id is already the id: one filter on the wire, one id in `searched`, and
    no collection lookup at all."""
    respx_mock.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=raw_model()))
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": [], "total": 0})
    )
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    out = await client.search_entities(collection="874", q="acme")
    assert _scopes(route.calls.last.request) == ["874"]
    assert out["searched"] == {"schemata": "Thing", "collection": ["874"]}
    assert lookup.call_count == 0, "a numeric id must not be resolved through the listing"


async def test_a_list_of_collections_emits_one_filter_per_id(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Aleph ORs repeated values within one filter key, so a multi-collection scope is a
    repeated parameter rather than a joined string. Order is asserted because `searched`
    is what a caller reads the scope back from, and it must describe what was sent."""
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    out = await client.search_entities(collection=["874", "42"], q="acme")
    assert _scopes(route.calls.last.request) == ["874", "42"]
    assert out["searched"] == {"schemata": "Thing", "collection": ["874", "42"]}


# -- opting out, deliberately and visibly --------------------------------------


async def test_the_all_collections_literal_drops_the_filter_and_annotates_the_reply(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """`"*"` is the one way to search everything, and it must be legible afterwards: an
    unscoped search whose rows look exactly like a scoped one's is the failure mode."""
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    out = await client.search_entities(collection=ALL_COLLECTIONS, q="acme")
    assert _scopes(route.calls.last.request) == [], "'*' must not be sent as a filter value"
    assert out["searched"] == {"schemata": "Thing", "collection": "*"}
    note = out.get("_note") or ""
    assert "EVERY COLLECTION:" in note, f"an unscoped search must say so in `_note`: {note!r}"


async def test_the_every_collection_note_composes_with_the_unenumerated_note(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Both are true of the same response — it was unscoped *and* its tail is unreachable
    — so one must not overwrite the other. Same composition rule as the shrink notes."""
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=MAX_PAGE + 1))
    )
    out = await client.search_entities(collection=ALL_COLLECTIONS, q="acme")
    note = out.get("_note") or ""
    assert "EVERY COLLECTION:" in note, f"the unscoped note must survive beside the other: {note!r}"
    assert "UNENUMERATED" in note, (
        f"the unreachable-tail note must survive beside the other: {note!r}"
    )


# -- foreign ids resolve, once -------------------------------------------------


async def test_a_foreign_id_is_resolved_to_its_numeric_id(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """A foreign_id used to be refused here, which forced a caller to convert it first.
    It now resolves through the listing, and the resolved *numeric* id is what reaches
    both the wire and `searched` — echoing the foreign_id back would leave a caller unable
    to tell which collection was actually searched."""
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [{"id": "874", "foreign_id": "my-case", "label": "Case files"}],
            },
        )
    )
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    out = await client.search_entities(collection="my-case", q="acme")
    assert lookup.call_count == 1
    assert ("filter:foreign_id", "my-case") in _query(lookup.calls.last.request)
    assert _scopes(route.calls.last.request) == ["874"]
    assert out["searched"]["collection"] == ["874"], "the resolved id, not the foreign_id"


async def test_a_foreign_id_is_looked_up_only_once_across_searches(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """A numeric id never changes, so the mapping is cached for the process lifetime.
    Without it every scoped call in a session pays an extra round trip, and a session
    works one or two collections for hundreds of searches."""
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [{"id": "874", "foreign_id": "my-case", "label": "Case files"}],
            },
        )
    )
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    first = await client.search_entities(collection="my-case", q="acme")
    second = await client.search_entities(collection="my-case", q="widgets")
    assert lookup.call_count == 1, "the second search must be served from the cache"
    assert route.call_count == 2, "both searches must still have been issued"
    assert first["searched"]["collection"] == second["searched"]["collection"] == ["874"]
    assert _scopes(route.calls.last.request) == ["874"], "the cached id must still be applied"


async def test_an_unresolvable_foreign_id_is_refused_and_names_list_collections(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """An unknown foreign_id is indistinguishable from one this key cannot read, so the
    refusal points at the tool that shows what is readable rather than guessing."""
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"total": 0, "results": []})
    )
    entities = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    with pytest.raises(ValueError, match="list_collections") as excinfo:
        await client.search_entities(collection="no-such-case", q="acme")
    assert "no-such-case" in str(excinfo.value), "the refusal must name the value it refused"
    assert lookup.call_count == 1
    assert entities.call_count == 0, "an unscopeable search must never be issued"


# -- one scope, one spelling ---------------------------------------------------


async def test_a_collection_id_in_filters_is_refused_rather_than_merged(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Two spellings for one scope is how the ambiguity survives its own fix. Merging them
    would answer a contradictory call successfully and leave the caller believing the
    other spelling worked, so it is refused, and the message says which argument to use
    and what to pass to it."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(ValueError) as excinfo:
        await client.search_entities(
            collection="874", filters={"collection_id": "42", "countries": ["ru"]}, q="acme"
        )
    message = str(excinfo.value)
    assert "`collection` argument" in message, message
    assert "42" in message, f"the message must name the value to move: {message}"
    assert wire.call_count == 0, "a refused call must cost no request"


async def test_no_tool_advertises_a_second_spelling_of_the_scope(server: FastMCP) -> None:
    """Read from the advertised JSON schemas, not the Python signatures: the schema is what
    a model is shown, and a tool could take `collection` internally while advertising
    `collection_id` to the caller."""
    async with MCPClient(server) as mcp:
        tools = await mcp.list_tools()
    advertised = {t.name: set((t.inputSchema or {}).get("properties") or {}) for t in tools}
    offenders = {
        name: sorted(props & FORBIDDEN_SCOPE_ARGS)
        for name, props in advertised.items()
        if props & FORBIDDEN_SCOPE_ARGS
    }
    assert not offenders, f"tools still advertise a second scope spelling: {offenders}"
    # The read above is only meaningful if the schemas were actually parsed: an empty or
    # misread `properties` would make the assertion vacuously true.
    scoped = {name for name, props in advertised.items() if "collection" in props}
    assert {"search_entities", "match_entity"} <= scoped, (
        f"scope-taking tools must advertise `collection`: {sorted(scoped)}"
    )


@pytest.mark.parametrize(
    ("collection", "expected"),
    [
        ([], "at least one collection"),
        ([ALL_COLLECTIONS, "874"], "cannot be combined with named collections"),
    ],
    ids=["empty-list", "star-mixed-with-an-id"],
)
async def test_a_list_that_names_no_usable_scope_is_refused(
    client: AlephClient,
    respx_mock: respx.MockRouter,
    collection: list[str],
    expected: str,
) -> None:
    """An empty list is a scope that selects nothing, and `["*", "874"]` asks for
    everything and for one collection at once. Both would otherwise resolve to something
    plausible — no filter at all, or a scope silently wider than the named ids — so both
    are refused, each naming what to pass instead."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(ValueError) as excinfo:
        await client.search_entities(collection=collection, q="acme")
    message = str(excinfo.value)
    assert expected in message, message
    assert ALL_COLLECTIONS in message, (
        f"the refusal must name the literal that does mean everything: {message}"
    )
    assert wire.call_count == 0, "a refused call must cost no request"


@pytest.mark.parametrize("collection", ["", "   ", "\n"], ids=["empty", "spaces", "newline"])
async def test_a_blank_collection_is_refused_before_any_request(
    client: AlephClient, respx_mock: respx.MockRouter, collection: str
) -> None:
    """The worst possible value, because Aleph does not read it as naming nothing.

    `sanitize_text` returns None for a blank string, so the filter set comes out empty
    and `field_filter_query` emits `match_all`: the listing answers with the first
    collection the key can read, `limit=1` takes it, and the search proceeds against a
    collection nobody named — with `searched` reporting a plausible id. An empty string is
    also the likeliest thing a model sends for a required argument it cannot fill, so this
    is refused locally, before the cache and before any request.
    """
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(ValueError, match="must not be empty"):
        await client.search_entities(collection=collection, q="acme")
    assert wire.call_count == 0, "a blank scope must not reach the wire"


async def test_a_resolved_hit_must_be_the_collection_that_was_asked_for(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The resolver ties the answer back to the question.

    Without this it trusts that the upstream applied the filter it was given, so any
    leniency — a dropped filter, a loose match, a redirect answered by a different listing
    — resolves to a plausible id for a collection nobody named and then caches it for the
    process lifetime. Here the listing answers with a different collection; that must be a
    refusal, not a search of collection 999.
    """
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200, json={"total": 1, "results": [{"id": "999", "foreign_id": "someone-else"}]}
        )
    )
    entities = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    with pytest.raises(ValueError, match="list_collections"):
        await client.search_entities(collection="my-case", q="acme")
    assert lookup.call_count == 1
    assert entities.call_count == 0, "an unverified resolution must not be searched"
    assert client._foreign_ids == {}, "a rejected resolution must never be cached"


async def test_a_non_dict_listing_row_is_a_tool_error_not_an_attribute_error(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """`_request` wraps a non-dict JSON body as `{"results": <body>}`, so a bare array
    upstream makes `results[0]` a string. `.get` on it would raise AttributeError, which
    no tool's `except ValueError` translates — the caller would see an unhandled exception
    instead of a legible refusal."""
    respx_mock.get("/api/2/collections").mock(return_value=httpx.Response(200, json=["x"]))
    with pytest.raises(ValueError, match="list_collections"):
        await client.search_entities(collection="my-case", q="acme")


async def test_paging_is_refused_before_a_foreign_id_costs_a_lookup(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The spec promises an over-window or negative-paging call sends no request at all.
    Resolution used to run first, so pairing a foreign_id with bad paging spent a lookup
    before the free check refused it — and the suite missed it because every paging test
    passed a numeric id."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    for kwargs in ({"limit": -1}, {"limit": 100, "offset": MAX_PAGE - 1}):
        with pytest.raises(ValueError):
            await client.search_entities(collection="fresh-case", q="acme", **kwargs)  # type: ignore[arg-type]
    assert wire.call_count == 0, "a refused call must not pay for a collection lookup"


async def test_a_scope_naming_too_many_collections_is_refused(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Each uncached foreign id is a whole upstream request with its own retry budget, so
    an unbounded list lets one tool call multiply that budget — the amplification the
    per-request budget and the shrink loop's deadline both exist to prevent."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(ValueError, match="at most"):
        await client.search_entities(collection=[f"case-{n}" for n in range(11)], q="acme")
    assert wire.call_count == 0


async def test_a_repeated_collection_costs_one_lookup(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Deduplicated before resolving, so a caller repeating an id in one list does not pay
    per occurrence, and the emitted filter set carries it once."""
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200, json={"total": 1, "results": [{"id": "874", "foreign_id": "my-case"}]}
        )
    )
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_entity(), total=1))
    )
    out = await client.search_entities(collection=["my-case", "my-case", "874"], q="acme")
    assert lookup.call_count == 1
    assert _scopes(route.calls.last.request) == ["874"]
    assert out["searched"]["collection"] == ["874"]


@pytest.mark.parametrize(
    "tool, args",
    [
        ("get_collection", {}),
        ("list_entitysets", {}),
        ("xref_results", {}),
    ],
)
async def test_the_all_collections_literal_is_refused_by_single_collection_tools(
    client: AlephClient, respx_mock: respx.MockRouter, tool: str, args: dict[str, object]
) -> None:
    """`"*"` is the all-collections literal for the two search tools only. On a tool that
    addresses exactly one collection it previously fell through to the foreign_id branch,
    spent a lookup, and failed with 'no collection with foreign_id "*"' — which contradicts
    the instruction paragraph teaching that `"*"` is this same argument's literal."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(ValueError, match="exactly one collection"):
        await getattr(client, tool)(collection=ALL_COLLECTIONS, **args)
    assert wire.call_count == 0


async def test_a_lookup_failure_is_reported_against_the_tool_that_was_called(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Before this, the resolver hard-coded `context="get_collection"`, so a failed lookup
    during a search told the model to check an id for a tool it never invoked."""
    respx_mock.get("/api/2/collections").mock(return_value=httpx.Response(503))
    with pytest.raises(Exception) as excinfo:
        await client.search_entities(collection="my-case", q="acme")
    assert "search_entities" in str(excinfo.value), str(excinfo.value)


async def test_an_upstream_id_echoed_into_an_error_is_bounded(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The `id` read out of a listing hit is upstream text, not caller text, and it reaches
    a model-visible error. This repo caps upstream material that reaches the model
    (`errors.py:_as_quoted_data`, `readonly.py:_describe`); an unbounded echo is a write
    primitive into the model's context."""
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            json={"total": 1, "results": [{"id": "n" * 5000, "foreign_id": "my-case"}]},
        )
    )
    with pytest.raises(ValueError) as excinfo:
        await client.search_entities(collection="my-case", q="acme")
    message = str(excinfo.value)
    assert len(message) < 500, f"upstream text echoed unbounded: {len(message)} chars"
    assert "chars]" in message, "the clip must say it clipped"
