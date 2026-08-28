import asyncio
import gzip
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from aleph_mcp.client import (
    MAX_EXPAND,
    MAX_FACET_SIZE,
    MAX_PAGE,
    MAX_PROPERTY_VALUES,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_SLEEP_SECS,
    AlephClient,
    derive_caption,
    slim_entity,
)
from tests.shapes import (
    BLOB_PROPS,
    assert_search_envelope,
    assert_slim_entity,
    raw_document,
    raw_entity,
    raw_model,
    raw_search_payload,
    unfence,
)


def _query(request: httpx.Request) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(str(request.url)).query, keep_blank_values=True)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the retry path without paying its backoff in wall-clock time."""

    async def _sleep(_: float) -> None:
        return None

    monkeypatch.setattr("aleph_mcp.client.asyncio.sleep", _sleep)


# -- slimming ------------------------------------------------------------------


def test_slim_entity_drops_text_blobs_and_reports_them() -> None:
    out = slim_entity(
        raw_entity(properties={"name": ["Jane"], "bodyText": ["x" * 5000], "indexText": ["y"]})
    )
    assert "bodyText" not in out["properties"]
    assert out["_omitted_properties"] == ["bodyText", "indexText"]
    assert out["properties"]["name"] == ["Jane"]


def test_slim_entity_truncates_long_values() -> None:
    out = slim_entity(raw_entity(properties={"summary": ["z" * 2000]}))
    value = out["properties"]["summary"][0]
    assert value.endswith("chars]")
    assert len(value) < 600


def test_slim_entity_keeps_highlight_and_score() -> None:
    out = slim_entity(raw_entity(highlight=["…hit…"], score=3.5))
    assert out["highlight"] == ["…hit…"]
    assert out["score"] == 3.5


def test_slim_entity_keeps_a_scalar_property_value() -> None:
    """Truncation applies per list item; a scalar value is passed through as it came."""
    out = slim_entity(raw_entity(properties={"summary": "z" * 2000}))
    assert out["properties"]["summary"] == "z" * 2000


def test_slim_entity_reduces_a_nested_entity_property_to_a_stub() -> None:
    """Aleph serialises entity-valued properties as WHOLE nested entities, links and all.

    Measured on the live gdx gateway 2026-08-28: one `PlainText` search hit spent ~800 of its
    characters on a single `parent` Folder — four absolute URLs, two timestamps and three
    housekeeping flags — to say the file sits in a folder named "files". Six searches put
    671,544 characters of tool result into one leg's prompt and drove it to 428,885 tokens
    against a 212,144 budget. The identity is all a model can act on; get_entity fetches the
    rest deliberately, which is the same bargain _TEXT_BLOB_PROPS already strikes.
    """
    nested = {
        "id": "14384680.08014cd",
        "schema": "Folder",
        "caption": None,
        "properties": {"fileName": ["files"], "bodyText": ["x" * 4000]},
        "created_at": "2026-03-12T14:24:00.828949",
        "updated_at": "2026-03-12T14:24:00.828957",
        "mutable": False,
        "writeable": True,
        "score": 1,
        "links": {
            "self": "https://aleph.example/api/2/entities/14384680.08014cd",
            "expand": "https://aleph.example/api/2/entities/14384680.08014cd/expand",
            "tags": "https://aleph.example/api/2/entities/14384680.08014cd/tags",
            "ui": "https://aleph.example/entities/14384680.08014cd",
        },
    }
    out = slim_entity(raw_entity(properties={"parent": [nested], "name": ["Jane"]}))

    stub = out["properties"]["parent"][0]
    assert stub == {"id": "14384680.08014cd", "schema": "Folder", "caption": "files"}
    assert "bodyText" not in str(stub)
    assert out["properties"]["name"] == ["Jane"]


def test_slim_entity_bounds_a_long_property_value_list() -> None:
    """NER fills `*Mentioned` lists without limit; bound them the way facets are bounded."""
    out = slim_entity(raw_entity(properties={"namesMentioned": [f"n{i}" for i in range(500)]}))
    values = out["properties"]["namesMentioned"]
    assert len(values) == MAX_PROPERTY_VALUES
    assert out["_omitted_values"] == {"namesMentioned": 500 - MAX_PROPERTY_VALUES}


# -- auth / transport ----------------------------------------------------------


async def test_sends_apikey_header(client: AlephClient, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": [], "total": 0})
    )
    await client.list_collections()
    assert route.calls.last.request.headers["Authorization"] == "ApiKey test_key"


async def test_retries_on_429_then_succeeds(
    client: AlephClient, respx_mock: respx.MockRouter, no_sleep: None
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"results": [], "total": 0}),
        ]
    )
    await client.list_collections()
    assert route.call_count == 2


async def test_a_hostile_retry_after_cannot_stall_past_the_timeout_budget(
    client: AlephClient, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each hop's delay is clamped, but the clamp times max_retries is the upstream's to
    spend unless one call shares one budget. httpx's timeout does not cover asyncio.sleep,
    so nothing else bounds this."""
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3600"})
    )
    with pytest.raises(ToolError, match="rate limited"):
        await client.list_collections()
    assert sum(slept) <= client._settings.timeout_secs
    assert max(slept) <= MAX_RETRY_SLEEP_SECS


async def test_gives_up_after_max_retries(
    client: AlephClient, respx_mock: respx.MockRouter, no_sleep: None
) -> None:
    route = respx_mock.get("/api/2/collections").mock(return_value=httpx.Response(503))
    with pytest.raises(ToolError, match="unexpected HTTP 503"):
        await client.list_collections()
    assert route.call_count == 4  # Settings.max_retries default


# Aleph's status codes are ambiguous on their own, so errors.py names the likely cause and
# the next move. Nothing else asserted that mapping.
HTTP_ERRORS = (
    (401, "API key invalid or expired"),
    (403, "not authorised"),
    (404, "not found"),
    (400, "bad request"),
    (429, "rate limited"),
    (500, "unexpected HTTP 500"),
)


@pytest.mark.parametrize(("status", "phrase"), HTTP_ERRORS, ids=[str(s) for s, _ in HTTP_ERRORS])
async def test_http_status_becomes_an_actionable_error(
    client: AlephClient, respx_mock: respx.MockRouter, no_sleep: None, status: int, phrase: str
) -> None:
    respx_mock.get("/api/2/entities/e1").mock(return_value=httpx.Response(status))
    with pytest.raises(ToolError, match=phrase):
        await client.get_entity(entity_id="e1")


async def test_request_wraps_a_bare_list_response(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Some Aleph routes answer with a bare JSON array; the client always returns a dict,
    so a caller never has to branch on the response type."""
    respx_mock.get("/api/2/entities/e1/tags").mock(
        return_value=httpx.Response(200, json=[{"field": "emails", "count": 2}])
    )
    out = await client.entity_tags(entity_id="e1")
    assert out["results"] == [{"field": "emails", "count": 2}]


async def test_unparseable_retry_after_falls_back_to_backoff(
    client: AlephClient, respx_mock: respx.MockRouter, no_sleep: None
) -> None:
    """Aleph is not required to send a numeric Retry-After. An unparseable one must not
    abort the retry — it falls back to exponential backoff."""
    route = respx_mock.get("/api/2/collections").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "soon"}),
            httpx.Response(200, json={"results": [], "total": 0}),
        ]
    )
    out = await client.list_collections()
    assert route.call_count == 2
    assert out["results"] == []


# -- collections ---------------------------------------------------------------


async def test_get_collection_by_numeric_id(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/collections/42").mock(
        return_value=httpx.Response(
            200, json={"id": "42", "foreign_id": "case", "label": "Case", "statistics": {}}
        )
    )
    out = await client.get_collection(collection="42")
    assert out["id"] == "42"
    assert "statistics" in out


async def test_get_collection_by_foreign_id(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    lookup = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "42", "foreign_id": "case", "label": "Case"}]}
        )
    )
    fetch = respx_mock.get("/api/2/collections/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "42",
                "foreign_id": "case",
                "label": "Case",
                "statistics": {"schema": {"values": {"Person": 3}}},
            },
        )
    )
    out = await client.get_collection(collection="case")
    assert out["id"] == "42"
    assert ("filter:foreign_id", "case") in _query(lookup.calls.last.request)
    assert fetch.call_count == 1


async def test_foreign_id_lookup_still_returns_statistics(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Regression: the listing endpoint carries no `statistics`, so answering the
    foreign_id branch straight from the listing hit returned `statistics: null` while
    the numeric branch returned the real block. Same tool, same promise, both branches."""
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "42", "foreign_id": "case"}]})
    )
    respx_mock.get("/api/2/collections/42").mock(
        return_value=httpx.Response(
            200, json={"id": "42", "statistics": {"schema": {"values": {"Person": 3}}}}
        )
    )
    by_fid = await client.get_collection(collection="case")
    by_id = await client.get_collection(collection="42")
    assert by_fid["statistics"] == by_id["statistics"]
    assert by_fid["statistics"]["schema"]["values"]["Person"] == 3


async def test_get_collection_unknown_foreign_id_is_actionable(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(ValueError, match="list_collections"):
        await client.get_collection(collection="nope")


async def test_negative_offset_is_refused(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(ValueError, match="offset must be >= 0"):
        await client.list_collections(offset=-1)
    assert wire.call_count == 0


async def test_numeric_collection_id_is_validated_before_interpolation(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """`"42\n"` reads as numeric intent, so it must be refused rather than falling through
    to the foreign_id branch and silently answering nothing."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(ValueError, match="invalid collection_id"):
        await client.get_collection(collection="42\n")
    assert wire.call_count == 0


# -- search --------------------------------------------------------------------


async def test_search_builds_filter_and_facet_params(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.search_entities(
        q="acme",
        filters={"collection_id": "42", "countries": ["ru", "cy"]},
        schema="Company",
        facets=["schema"],
        limit=0,
    )
    q = _query(route.calls.last.request)
    assert ("q", "acme") in q
    assert ("filter:collection_id", "42") in q
    assert ("filter:countries", "ru") in q
    assert ("filter:countries", "cy") in q
    assert ("filter:schema", "Company") in q
    assert ("facet", "schema") in q
    assert ("facet_size:schema", "20") in q
    assert ("facet_total:schema", "true") in q


async def test_search_rejects_deep_pagination(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="facets"):
        await client.search_entities(limit=50, offset=MAX_PAGE)


@pytest.mark.parametrize("facet_size", [0, MAX_FACET_SIZE + 1], ids=["zero", "over-cap"])
async def test_search_rejects_an_unbounded_facet_size(
    client: AlephClient, respx_mock: respx.MockRouter, facet_size: int
) -> None:
    """facet_size was the one pagination-shaped parameter with no cap, and it is the one
    the row limit does not cover: buckets are an aggregation, not a page of results."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="facet_size must be between"):
        await client.search_entities(facets=["schema"], facet_size=facet_size)
    assert wire.call_count == 0


async def test_facet_buckets_are_bounded_and_their_labels_truncated(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Facets skipped the slimmer entirely, so bucket labels — entity names, file names —
    reached the model untouched and unbounded in number."""
    buckets = [{"id": str(i), "label": "z" * 2000, "count": 1} for i in range(MAX_FACET_SIZE + 5)]
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [],
                "total": {"value": 0},
                "facets": {"names": {"total": len(buckets), "values": buckets}},
            },
        )
    )
    out = await client.search_entities(facets=["names"], limit=0)
    names = out["facets"]["names"]
    assert len(names["values"]) == MAX_FACET_SIZE
    assert names["_omitted_values"] == 5
    assert names["total"] == MAX_FACET_SIZE + 5, "the true bucket count must survive clipping"
    assert names["values"][0]["label"].endswith("chars]")


async def test_a_response_over_the_ceiling_is_refused_before_decoding(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    oversized = b'{"padding": "' + b"z" * (MAX_RESPONSE_BYTES + 1) + b'"}'
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200, content=oversized, headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(ToolError, match=r"over the .* ceiling"):
        await client.list_collections()


async def test_a_compressed_body_is_refused_on_its_expanded_size(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The ceiling has to bound the allocation, not describe it afterwards. httpx decodes
    Content-Encoding as the body is iterated, so a small transfer that expands past the
    ceiling must be refused at the same threshold as a large one."""
    payload = b'{"padding": "' + b"z" * (MAX_RESPONSE_BYTES + 1) + b'"}'
    compressed = gzip.compress(payload)
    assert len(compressed) < 1024 * 1024, "the point is that the wire transfer is small"
    respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            content=compressed,
            headers={"content-type": "application/json", "content-encoding": "gzip"},
        )
    )
    with pytest.raises(ToolError, match=r"over the .* ceiling"):
        await client.list_collections()


async def test_search_allows_the_exact_ceiling(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.search_entities(limit=9, offset=MAX_PAGE - 9)


async def test_search_notes_unreachable_tail(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 50000}})
    )
    out = await client.search_entities(q="a")
    assert "UNENUMERATED" in out["_note"]


async def test_search_strips_text_from_hits(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(raw_document()))
    )
    out = await client.search_entities(q="jane")
    assert_search_envelope(out, searched={"schemata": "Thing"})
    assert out["results"][0]["_omitted_properties"] == sorted(BLOB_PROPS)


async def test_highlight_only_when_query_present(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.search_entities(highlight=True)
    assert ("highlight", "true") not in _query(route.calls.last.request)


async def test_reachable_total_carries_no_note(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The UNENUMERATED note is a warning about an unreachable tail; a long-but-reachable
    result set must not carry it, or the warning stops meaning anything."""
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(total=500))
    )
    out = await client.search_entities(q="a")
    assert_search_envelope(out, searched={"schemata": "Thing"})
    assert "_note" not in out


@pytest.mark.parametrize("args", [{"limit": -1}, {"offset": -1}])
async def test_search_rejects_negative_paging(
    client: AlephClient, respx_mock: respx.MockRouter, args: dict[str, int]
) -> None:
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="must be >= 0"):
        await client.search_entities(**args)
    assert wire.call_count == 0


async def test_highlight_is_sent_when_a_query_is_present(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json=raw_search_payload(total=0))
    )
    await client.search_entities(q="acme", highlight=True)
    q = _query(route.calls.last.request)
    assert ("highlight", "true") in q
    assert ("highlight_count", "3") in q


# -- entity, expand ------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a b", "e1/x", ""])
async def test_entity_id_validation(client: AlephClient, bad: str) -> None:
    with pytest.raises(ValueError, match="invalid entity_id"):
        await client.get_entity(entity_id=bad)


async def test_expand_rejects_limit_above_cap(client: AlephClient) -> None:
    with pytest.raises(ValueError, match=str(MAX_EXPAND)):
        await client.expand_entity(entity_id="e1", limit=MAX_EXPAND + 1)


async def test_expand_passes_property_filters_and_slims(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities/e1/expand").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "property": "ownershipOwner",
                        "count": 7,
                        "entities": [raw_document()],
                    }
                ],
            },
        )
    )
    out = await client.expand_entity(entity_id="e1", properties=["ownershipOwner"], limit=10)
    assert ("filter:property", "ownershipOwner") in _query(route.calls.last.request)
    assert out["results"][0]["count"] == 7
    assert_slim_entity(out["results"][0]["entities"][0])


async def test_get_entity_strips_document_text(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/d1").mock(return_value=httpx.Response(200, json=raw_document()))
    out = await client.get_entity(entity_id="d1")
    assert out["_omitted_properties"] == sorted(BLOB_PROPS)
    assert_slim_entity(out)


async def test_nothing_dropped_means_no_omitted_marker(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The marker names what was left out, so it must be absent when nothing was."""
    respx_mock.get("/api/2/entities/e1").mock(return_value=httpx.Response(200, json=raw_entity()))
    out = await client.get_entity(entity_id="e1")
    assert "_omitted_properties" not in out
    assert_slim_entity(out)


@pytest.mark.parametrize("entity_id", ["e1\n", "e1\r", "e1\n\n", "e1 "])
async def test_ids_with_trailing_whitespace_are_refused(
    client: AlephClient, respx_mock: respx.MockRouter, entity_id: str
) -> None:
    """Regression for 7d6c175: the validators used `$`, which matches before a trailing
    newline, so `"e1\n"` passed here and was then refused by the read-only guard with a
    misleading message — or, on a path that does not re-check, sent as-is."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="invalid entity_id"):
        await client.get_entity(entity_id=entity_id)
    assert wire.call_count == 0


# Every method that interpolates a caller id into a path. An id of only dot segments
# passes the charset and is then normalised away at URL construction, so
# `/api/2/entitysets/../entities` would answer a different question than was asked.
ID_METHODS = (
    ("get_entity", "entity_id"),
    ("entity_tags", "entity_id"),
    ("expand_entity", "entity_id"),
    ("similar_entities", "entity_id"),
    ("get_entity_text", "entity_id"),
    ("get_profile", "profile_id"),
    ("profile_tags", "profile_id"),
    ("profile_similar", "profile_id"),
    ("expand_profile", "profile_id"),
    ("get_entityset", "entityset_id"),
    ("entityset_items", "entityset_id"),
)


@pytest.mark.parametrize("bad", ["..", ".", "...", "./."])
@pytest.mark.parametrize(("method", "field"), ID_METHODS, ids=[name for name, _ in ID_METHODS])
async def test_id_that_addresses_nothing_is_refused(
    client: AlephClient, respx_mock: respx.MockRouter, method: str, field: str, bad: str
) -> None:
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(ValueError, match=f"invalid {field}"):
        await getattr(client, method)(**{field: bad})
    assert wire.call_count == 0


async def test_dotted_ids_are_still_accepted(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The dot-only refusal must not become a ban on dots — real Aleph ids contain them."""
    respx_mock.get("/api/2/entities/a.b.c").mock(
        return_value=httpx.Response(200, json=raw_entity(id="a.b.c"))
    )
    out = await client.get_entity(entity_id="a.b.c")
    assert out["id"] == "a.b.c"


# -- match ---------------------------------------------------------------------


async def test_match_requires_schema(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="schema"):
        await client.match_entity(sample={"properties": {"name": ["x"]}})


async def test_match_posts_sample(client: AlephClient, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/api/2/match").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    await client.match_entity(
        sample={"schema": "Person", "properties": {"name": ["Jane"]}}, collection_ids=["42"]
    )
    assert ("collection_ids", "42") in _query(route.calls.last.request)


async def test_collection_id_validation_rejects_foreign_id(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="get_collection"):
        await client.xref_results(collection_id="my-case")


# -- profiles ------------------------------------------------------------------


async def test_expand_profile_rejects_limit_above_cap(client: AlephClient) -> None:
    with pytest.raises(ValueError, match=str(MAX_EXPAND)):
        await client.expand_profile(profile_id="p1", limit=MAX_EXPAND + 1)


async def test_expand_profile_passes_property_filters_and_slims(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/profiles/p1/expand").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "property": "ownershipOwner",
                        "count": 7,
                        "entities": [raw_document()],
                    }
                ],
            },
        )
    )
    out = await client.expand_profile(profile_id="p1", properties=["ownershipOwner"], limit=10)
    assert ("filter:property", "ownershipOwner") in _query(route.calls.last.request)
    assert out["results"][0]["count"] == 7
    assert_slim_entity(out["results"][0]["entities"][0])


async def test_get_profile_slims_the_merged_entity(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """`merged` combines the profile's constituents, so a merged-in Document drags its
    bodyText along. It has to go through slim_entity like any other entity."""
    respx_mock.get("/api/2/profiles/p1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "p1",
                "type": "profile",
                "label": "Jane Doe",
                "collection": {"id": "42"},
                "entities": ["e1", "e2"],
                "merged": raw_entity(properties={"bodyText": ["x" * 50], "name": ["Jane Doe"]}),
            },
        )
    )
    out = await client.get_profile(profile_id="p1")
    assert out["entities"] == ["e1", "e2"]
    assert out["collection_id"] == "42"
    assert "bodyText" not in out["merged"]["properties"]
    assert out["merged"]["_omitted_properties"] == ["bodyText"]


async def test_get_profile_drops_the_latinized_block(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """ProfileSerializer adds a transliteration of every name already in `properties`."""
    respx_mock.get("/api/2/profiles/p1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "p1",
                "type": "profile",
                "merged": raw_entity(),
                "latinized": {"name": ["Zhanna Doe"]},
            },
        )
    )
    out = await client.get_profile(profile_id="p1")
    assert "latinized" not in out
    assert "latinized" not in out["merged"]


async def test_profile_tags_gets_the_same_bounding_as_entity_tags(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    payload = {"status": "ok", "total": 1, "results": [{"field": "phones", "count": 3}]}
    respx_mock.get("/api/2/profiles/p1/tags").mock(return_value=httpx.Response(200, json=payload))
    out = await client.profile_tags(profile_id="p1")
    assert out["results"] == payload["results"]
    assert out["total"] == 1
    assert out["_provenance"]["trust"] == "untrusted"


async def test_profile_similar_reports_score_and_judgement(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/profiles/p1/similar").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [{"score": 4.5, "judgement": None, "entity": raw_entity()}],
            },
        )
    )
    out = await client.profile_similar(profile_id="p1")
    assert out["results"][0]["score"] == 4.5
    assert out["results"][0]["judgement"] is None
    assert out["results"][0]["entity"]["id"] == "e1"
    assert_slim_entity(out["results"][0]["entity"])


async def test_get_entityset_reports_a_profile_without_following_the_redirect(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Aleph 302s this route to the profile view, but builds the Location from its
    configured PUBLIC UI url — a different host:port from the API on a real deployment,
    which strips auth and 403s. Verified live: Location was localhost:8080 for an API on
    :5000. So the redirect must be read, not followed."""
    route = respx_mock.get("/api/2/entitysets/p1").mock(
        return_value=httpx.Response(
            302, headers={"Location": "http://ui.example:8080/api/2/profiles/p1"}
        )
    )
    followed = respx_mock.get("http://ui.example:8080/api/2/profiles/p1").mock(
        return_value=httpx.Response(200, json={"id": "p1", "type": "profile"})
    )
    out = await client.get_entityset(entityset_id="p1")
    assert out["type"] == "profile"
    assert out["id"] == "p1"
    assert "get_profile" in out["_note"]
    assert route.call_count == 1
    assert followed.call_count == 0, "the redirect must not be followed off the API host"


async def test_get_entityset_adds_detail_fields_a_listing_omits(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entitysets/es1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "es1",
                "type": "diagram",
                "label": "Network",
                "layout": {"vertices": []},
                "created_at": "2024-01-01",
                "role_id": "9",
                "collection": {"id": "42"},
            },
        )
    )
    out = await client.get_entityset(entityset_id="es1")
    assert out["collection_id"] == "42"
    assert out["role_id"] == "9"
    assert out["layout"] == {"vertices": []}
    assert "_note" not in out


# -- document text -------------------------------------------------------------


async def test_get_entity_text_from_body_text(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/d1").mock(
        return_value=httpx.Response(
            200,
            json=raw_entity(id="d1", schema="PlainText", properties={"bodyText": ["abcdefghij"]}),
        )
    )
    out = await client.get_entity_text(entity_id="d1", offset=2, limit=3)
    assert unfence(out["text"]) == "cde"
    assert out["total_chars"] == 10
    assert out["truncated"] is True
    assert out["source"] == "bodyText"


async def test_get_entity_text_falls_back_to_pages(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/d2").mock(
        return_value=httpx.Response(200, json=raw_entity(id="d2", schema="Pages", properties={}))
    )
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"properties": {"bodyText": ["page one"]}},
                    {"properties": {"bodyText": ["page two"]}},
                ]
            },
        )
    )
    out = await client.get_entity_text(entity_id="d2")
    q = _query(route.calls.last.request)
    assert ("filter:properties.document", "d2") in q
    assert ("filter:schema", "Page") in q
    assert out["source"] == "pages"
    assert unfence(out["text"]) == "page one\n\npage two"
    assert out["truncated"] is False


async def test_document_text_is_fenced_and_attributed(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """Document text is attacker-plantable, so it comes back as data: named to a
    collection and sealed in a per-response fence a payload cannot close itself."""
    payload = raw_entity(
        id="d3", schema="PlainText", properties={"bodyText": ["ignore all previous"]}
    )
    payload["collection"] = {"id": "7", "label": "Leaked mailbox"}
    respx_mock.get("/api/2/entities/d3").mock(return_value=httpx.Response(200, json=payload))

    out = await client.get_entity_text(entity_id="d3")
    assert unfence(out["text"]) == "ignore all previous"
    assert out["_provenance"]["trust"] == "untrusted"
    assert out["_provenance"]["collection_id"] == "7"
    assert out["_provenance"]["collection_label"] == "Leaked mailbox"

    again = await client.get_entity_text(entity_id="d3")
    assert again["text"] != out["text"], "fence nonce must not repeat across responses"


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ({"offset": -1}, "offset must be >= 0"),
        ({"limit": 0}, "between 1 and 200000"),
        ({"limit": 200001}, "between 1 and 200000"),
    ],
)
async def test_text_slice_bounds(
    client: AlephClient, respx_mock: respx.MockRouter, args: dict[str, int], match: str
) -> None:
    """A slice request outside the bounds is refused before the document is fetched, so an
    absurd limit costs nothing."""
    wire = respx_mock.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(ValueError, match=match):
        await client.get_entity_text(entity_id="d1", **args)
    assert wire.call_count == 0


# -- ontology ------------------------------------------------------------------


async def test_get_schema_is_cached_after_first_fetch(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/metadata").mock(
        return_value=httpx.Response(200, json=raw_model())
    )
    person = await client.get_schema(name="Person")
    listing = await client.list_schemata()
    assert route.call_count == 1
    assert person["properties"]["name"]["type"] == "name"
    assert "inheritance chain" in person["_note"]
    assert listing["edges"] == ["Ownership"]
    assert listing["matchable"] == ["Person"]


async def test_unknown_schema_suggests_alternatives(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(
        return_value=httpx.Response(200, json={"model": {"schemata": {"Person": {}}}})
    )
    with pytest.raises(ValueError, match="Did you mean"):
        await client.get_schema(name="Persson")


# -- mandatory schema scope (regression: live 400 "No schema is specified") -----


async def test_search_applies_default_schemata_when_none_given(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    out = await client.search_entities(q="acme")
    assert ("filter:schemata", "Thing") in _query(route.calls.last.request)
    assert out["searched"] == {"schemata": "Thing"}


async def test_explicit_schemata_wins_over_the_default(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    out = await client.search_entities(schemata="Interval")
    q = _query(route.calls.last.request)
    assert ("filter:schemata", "Interval") in q
    assert ("filter:schemata", "Thing") not in q
    assert out["searched"] == {"schemata": "Interval"}


async def test_exact_schema_suppresses_the_schemata_default(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(200, json={"results": [], "total": {"value": 0}})
    )
    out = await client.search_entities(schema="Ownership")
    q = _query(route.calls.last.request)
    assert ("filter:schema", "Ownership") in q
    assert not [v for k, v in q if k == "filter:schemata"]
    assert out["searched"] == {"schema": "Ownership"}


# -- caption / provenance (regression: live Aleph returns caption=null) ---------


def test_derive_caption_uses_fallback_order_when_no_model() -> None:
    assert derive_caption({"schema": "Person", "properties": {"name": ["Jane"]}}) == "Jane"
    assert derive_caption({"schema": "Document", "properties": {"fileName": ["a.pdf"]}}) == "a.pdf"


def test_derive_caption_prefers_the_schema_declared_order() -> None:
    schemata = {"LegalEntity": {"caption": ["registrationNumber", "name"]}}
    entity = {
        "schema": "LegalEntity",
        "properties": {"name": ["Acme"], "registrationNumber": ["RU-1"]},
    }
    assert derive_caption(entity, schemata) == "RU-1"
    assert derive_caption(entity) == "Acme"  # fallback order prefers name


def test_derive_caption_keeps_a_server_supplied_caption() -> None:
    assert derive_caption({"caption": "Given", "properties": {"name": ["Other"]}}) == "Given"


def test_derive_caption_returns_none_when_nothing_matches() -> None:
    assert derive_caption({"schema": "Page", "properties": {"index": [3]}}) is None


def test_derive_caption_accepts_a_scalar_property_value() -> None:
    """FtM property values are lists by convention, but Aleph does not guarantee it."""
    assert derive_caption({"schema": "Person", "properties": {"name": "Jane"}}) == "Jane"


def test_slim_entity_reads_the_nested_collection_object() -> None:
    out = slim_entity({"id": "e1", "schema": "Person", "collection": {"id": 583, "label": "x"}})
    assert out["collection_id"] == "583"


def test_slim_entity_prefers_an_explicit_collection_id() -> None:
    """Not every payload nests: entityset records carry `collection_id` directly. When both
    are present the explicit field wins, so provenance never depends on which shape arrived."""
    out = slim_entity(
        {"id": "e1", "schema": "Person", "collection_id": 583, "collection": {"id": 7}}
    )
    assert out["collection_id"] == "583"


async def test_search_derives_captions_from_the_instance_model(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/metadata").mock(
        return_value=httpx.Response(
            200, json={"model": {"schemata": {"Person": {"caption": ["name"]}}}}
        )
    )
    respx_mock.get("/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "id": "p1",
                        "schema": "Person",
                        "caption": None,
                        "collection": {"id": 583},
                        "properties": {"name": ["Jane Doe"]},
                    }
                ],
            },
        )
    )
    out = await client.search_entities(schema="Person")
    hit = out["results"][0]
    assert hit["caption"] == "Jane Doe"
    assert hit["collection_id"] == "583"


# -- listing, pivots and cross-referencing -------------------------------------
#
# These six methods were reached only incidentally, by the read-only tripwires that
# drive every endpoint to prove none of them writes. Nothing asserted what they give
# back, so any reshaping regression in them was invisible.


async def test_list_collections_slims_and_passes_the_label_filter(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "limit": 30,
                "offset": 0,
                "results": [
                    {
                        "id": "42",
                        "foreign_id": "case",
                        "label": "Case files",
                        "category": "casefile",
                        "casefile": True,
                        "countries": ["ua"],
                        "updated_at": "2024-01-01T00:00:00",
                        "writeable": False,
                        "links": {"ui": "https://aleph.test/datasets/42"},
                        "secret": True,
                    }
                ],
            },
        )
    )
    out = await client.list_collections(q="case")
    assert ("q", "case") in _query(route.calls.last.request)
    assert (out["total"], out["limit"], out["offset"]) == (1, 30, 0)
    hit = out["results"][0]
    assert hit["id"] == "42"
    assert hit["countries"] == ["ua"]
    # The listing view carries no statistics, so it must not claim one, and the
    # server's own bookkeeping is not worth a model's context.
    assert "statistics" not in hit
    assert "links" not in hit


async def test_list_collections_omits_the_query_when_none_given(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    await client.list_collections()
    assert [k for k, _ in _query(route.calls.last.request)] == ["limit", "offset"]


async def test_list_collections_rejects_a_limit_above_the_listing_cap(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(ValueError, match="100"):
        await client.list_collections(limit=101)
    assert route.call_count == 0


async def test_entity_tags_is_bounded_and_labelled(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """A tags response aggregates values lifted out of third-party documents, and the
    endpoint accepts no limit — so the row count is the upstream's to choose unless this
    end caps it. Same treatment as a facets block."""
    tags = [
        {"id": f"name:x{i}", "field": "names", "value": "z" * 2000, "count": 1}
        for i in range(MAX_FACET_SIZE + 3)
    ]
    route = respx_mock.get("/api/2/entities/e1/tags").mock(
        return_value=httpx.Response(200, json={"status": "ok", "total": len(tags), "results": tags})
    )
    out = await client.entity_tags(entity_id="e1")
    assert len(out["results"]) == MAX_FACET_SIZE
    assert out["_omitted_values"] == 3
    assert out["total"] == len(tags), "the true count must survive the clipping"
    assert out["results"][0]["value"].endswith("chars]")
    assert out["_provenance"]["trust"] == "untrusted"
    assert "status" not in out, "upstream envelope keys are not passed through"
    assert route.call_count == 1


async def test_similar_entities_reports_score_judgement_and_a_slim_entity(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entities/e1/similar").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "score": 4.5,
                        "judgement": "positive",
                        "entity": raw_entity(
                            id="e2", properties={"name": ["Jane Doe"], "indexText": ["huge"]}
                        ),
                    }
                ],
            },
        )
    )
    out = await client.similar_entities(entity_id="e1", limit=5)
    assert ("limit", "5") in _query(route.calls.last.request)
    hit = out["results"][0]
    assert (hit["score"], hit["judgement"]) == (4.5, "positive")
    assert hit["entity"]["id"] == "e2"
    assert_slim_entity(hit["entity"])


async def test_similar_entities_survives_a_result_with_no_entity(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1/similar").mock(
        return_value=httpx.Response(200, json={"total": 1, "results": [{"score": 1.0}]})
    )
    out = await client.similar_entities(entity_id="e1")
    hit = out["results"][0]
    assert hit["score"] == 1.0
    assert hit["judgement"] is None
    assert hit["entity"]["id"] is None
    assert hit["entity"]["properties"] == {}


async def test_list_entitysets_filters_by_collection_and_type(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entitysets").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "id": "es1",
                        "type": "diagram",
                        "label": "Network",
                        "summary": "who pays whom",
                        "entities": ["e1", "e2"],
                        "updated_at": "2024-01-01T00:00:00",
                        "role": {"name": "Curator"},
                    }
                ],
            },
        )
    )
    out = await client.list_entitysets(collection_id="42", set_type="diagram")
    q = _query(route.calls.last.request)
    assert ("filter:collection_id", "42") in q
    assert ("filter:type", "diagram") in q
    hit = out["results"][0]
    assert (hit["id"], hit["type"], hit["label"]) == ("es1", "diagram", "Network")
    assert hit["summary"] == "who pays whom"


async def test_list_entitysets_rejects_a_foreign_id(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="numeric id"):
        await client.list_entitysets(collection_id="my-case")


async def test_entityset_items_slims_and_pages(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entitysets/es1/entities").mock(
        return_value=httpx.Response(
            200,
            json=raw_search_payload(raw_document()),
        )
    )
    out = await client.entityset_items(entityset_id="es1", limit=10, offset=5)
    q = _query(route.calls.last.request)
    assert ("limit", "10") in q and ("offset", "5") in q
    assert_search_envelope(out)
    assert out["total"] == 1
    assert out["results"][0]["_omitted_properties"] == sorted(BLOB_PROPS)


async def test_entityset_items_refuses_a_limit_above_the_cap(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/entitysets/es1/entities").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(ValueError, match="200"):
        await client.entityset_items(entityset_id="es1", limit=201)
    assert route.call_count == 0


async def test_xref_results_pairs_both_sides_of_the_match(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/api/2/collections/42/xref").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "limit": 30,
                "offset": 0,
                "results": [
                    {
                        "score": 3.25,
                        "judgement": "unsure",
                        "entity": raw_entity(id="e1"),
                        "match": raw_document(id="m1"),
                        "match_collection_id": "77",
                    }
                ],
            },
        )
    )
    out = await client.xref_results(collection_id="42", limit=30)
    assert ("limit", "30") in _query(route.calls.last.request)
    hit = out["results"][0]
    assert (hit["score"], hit["judgement"]) == (3.25, "unsure")
    # Provenance is the whole point of an xref hit: which collection the match is from.
    assert hit["match_collection_id"] == "77"
    assert hit["entity"]["id"] == "e1"
    assert hit["match"]["id"] == "m1"
    assert_slim_entity(hit["entity"])
    assert_slim_entity(hit["match"])


async def test_xref_results_rejects_a_foreign_id(client: AlephClient) -> None:
    with pytest.raises(ValueError, match="numeric id"):
        await client.xref_results(collection_id="my-case")
