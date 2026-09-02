import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from aleph_mcp.client import AlephClient
from aleph_mcp.readonly import ReadOnlyViolation, is_read_only, read_only_hook


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/2/metadata"),
        ("GET", "/api/2/collections"),
        ("GET", "/api/2/collections/42"),
        ("GET", "/api/2/collections/42/xref"),
        ("GET", "/api/2/entities"),
        ("GET", "/api/2/entities/e1"),
        ("GET", "/api/2/entities/e1/expand"),
        ("GET", "/api/2/entities/e1/similar"),
        ("GET", "/api/2/entities/e1/tags"),
        ("GET", "/api/2/profiles/p1"),
        ("GET", "/api/2/profiles/p1/expand"),
        ("GET", "/api/2/profiles/p1/similar"),
        ("GET", "/api/2/profiles/p1/tags"),
        ("GET", "/api/2/entitysets"),
        ("GET", "/api/2/entitysets/es1"),
        ("GET", "/api/2/entitysets/es1/entities"),
        ("POST", "/api/2/match"),
    ],
)
def test_client_endpoints_are_allowed(method: str, path: str) -> None:
    assert is_read_only(method, path)


def test_trailing_slash_is_allowed() -> None:
    assert is_read_only("GET", "/api/2/entities/")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/2/entities"),
        ("PUT", "/api/2/entities/e1"),
        ("PATCH", "/api/2/entities/e1"),
        ("DELETE", "/api/2/entities/e1"),
        ("DELETE", "/api/2/collections/42"),
        ("POST", "/api/2/collections/42/reingest"),
        ("POST", "/api/2/collections/42/xref"),
        ("POST", "/api/2/collections/42/bulk"),
        ("POST", "/api/2/entitysets"),
        ("POST", "/api/2/ingest"),
        ("POST", "/api/2/roles/1"),
        ("GET", "/api/2/collections/42/reingest"),
    ],
)
def test_write_requests_are_blocked(method: str, path: str) -> None:
    assert not is_read_only(method, path)


def test_id_cannot_widen_the_path() -> None:
    assert not is_read_only("GET", "/api/2/entities/e1/delete")
    assert not is_read_only("GET", "/api/2/collections/case/xref")


def test_pairwise_judgement_is_blocked() -> None:
    """POST /api/2/profiles/_pairwise records a judgement and can create or merge a
    profile — an Aleph write. Its path matches the GET rule for /api/2/profiles/<id>,
    because the accepted id charset includes `_`. Nothing but the method pin refuses it,
    so assert that directly: this is the one allowlist entry where pairing a method with
    the path is load-bearing rather than belt-and-braces.
    """
    assert is_read_only("GET", "/api/2/profiles/_pairwise")
    assert not is_read_only("POST", "/api/2/profiles/_pairwise")
    assert not is_read_only("POST", "/api/2/profiles/p1")


@pytest.mark.parametrize("method", ["DELETE", "POST", "PUT"])
def test_entityset_detail_writes_are_blocked_on_method_alone(method: str) -> None:
    """`/api/2/entitysets/<id>` is allowlisted for GET, and upstream Aleph registers
    DELETE, POST and PUT on that exact same path (entitysets_api.py:144,181) — verified
    against a live instance, which answers 405 for a method it does not route and 404
    here. Nothing but the missing (method, path) pair refuses these, so assert it: this
    is the case where reading the path rule alone would suggest the surface is safe."""
    path = "/api/2/entitysets/es1"
    assert is_read_only("GET", path)
    assert not is_read_only(method, path)
    assert not is_read_only(method, f"{path}/entities")


async def test_direct_write_through_the_client_never_reaches_the_wire(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post("/api/2/collections/42/reingest").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(ReadOnlyViolation):
        await client._http.post("/api/2/collections/42/reingest", json={})
    assert route.call_count == 0


async def test_redirect_into_a_write_endpoint_is_blocked(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1").mock(
        return_value=httpx.Response(307, headers={"Location": "/api/2/collections/42/reingest"})
    )
    blocked = respx_mock.get("/api/2/collections/42/reingest").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(ToolError, match="read-only"):
        await client.get_entity(entity_id="e1")
    assert blocked.call_count == 0


async def test_empty_path_is_normalised_to_root() -> None:
    """An Aleph mounted under a path prefix: a request to the prefix itself leaves an empty
    API-relative path, which is read as `/` and refused. No allowlist rule matches `/`, and
    an empty string would have matched nothing either — but only by accident."""
    hook = read_only_hook("https://aleph.test/aleph")
    with pytest.raises(ReadOnlyViolation, match="read-only"):
        await hook(httpx.Request("GET", "https://aleph.test/aleph"))


async def test_base_path_prefix_is_stripped_before_matching() -> None:
    hook = read_only_hook("https://aleph.test/aleph")
    await hook(httpx.Request("GET", "https://aleph.test/aleph/api/2/entities"))
    with pytest.raises(ReadOnlyViolation, match="read-only"):
        await hook(httpx.Request("POST", "https://aleph.test/aleph/api/2/entities"))
    with pytest.raises(ReadOnlyViolation, match="base path"):
        await hook(httpx.Request("GET", "https://aleph.test/api/2/entities"))


async def test_request_leaving_the_configured_origin_is_blocked() -> None:
    hook = read_only_hook("https://aleph.test")
    with pytest.raises(ReadOnlyViolation, match="configured Aleph origin"):
        await hook(httpx.Request("GET", "https://evil.example/api/2/entities"))


@pytest.mark.parametrize(
    "url",
    [
        "http://aleph.test/api/2/entities",
        "https://aleph.test:9200/api/2/entities",
    ],
    ids=["cleartext-downgrade", "other-port-same-machine"],
)
async def test_same_hostname_on_another_scheme_or_port_is_blocked(url: str) -> None:
    """The pin is the origin, not the hostname. A redirect that keeps the hostname but
    downgrades the scheme, or names another service's port, is a different destination and
    is refused before the allowlist ever sees the path."""
    hook = read_only_hook("https://aleph.test")
    with pytest.raises(ReadOnlyViolation, match="configured Aleph origin"):
        await hook(httpx.Request("GET", url))


async def test_the_default_port_is_the_same_origin_as_no_port() -> None:
    """Otherwise the pin would refuse the instance's own canonical redirect."""
    hook = read_only_hook("https://aleph.test")
    await hook(httpx.Request("GET", "https://aleph.test:443/api/2/entities"))
    await read_only_hook("http://aleph.test:80")(
        httpx.Request("GET", "http://aleph.test/api/2/entities")
    )


async def test_a_refusal_does_not_echo_the_query_or_a_hostile_redirect_target() -> None:
    """On a redirect hop the URL comes from the upstream's Location header, so the refusal
    message is a channel into the model's context. It gets the same treatment as upstream
    error text: bounded, control-characters replaced, and no query string."""
    hook = read_only_hook("https://aleph.test")
    hostile = "https://evil.example/" + "z" * 400 + "?q=analyst-search-term"
    with pytest.raises(ReadOnlyViolation) as exc:
        await hook(httpx.Request("GET", hostile))
    message = str(exc.value)
    assert "analyst-search-term" not in message
    assert "…" in message
    assert len(message) < 300


async def test_a_refusal_never_prints_host_userinfo() -> None:
    """httpx renders userinfo unmasked in str(), and config refuses such a host outright —
    but the guard is reachable with a redirect target that carries one."""
    hook = read_only_hook("https://aleph.test")
    with pytest.raises(ReadOnlyViolation) as exc:
        await hook(httpx.Request("GET", "https://svc:hunter2@evil.example/api/2/entities"))
    assert "hunter2" not in str(exc.value)


async def test_cross_host_redirect_is_blocked(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://evil.example/api/2/entities"}
        )
    )
    with pytest.raises(ToolError, match="configured Aleph origin"):
        await client.get_entity(entity_id="e1")


# -- allowlist shape ----------------------------------------------------------


def test_allowlist_carries_no_mutating_verb() -> None:
    """The tuple is the only thing that can widen the surface, so its shape is contract."""
    from aleph_mcp.readonly import _ALLOWED

    non_get = [(m, p.pattern) for m, p in _ALLOWED if m != "GET"]
    assert len(non_get) == 1
    method, pattern = non_get[0]
    assert method == "POST"
    assert "/api/2/match" in pattern


# -- redirect coverage --------------------------------------------------------


async def test_guard_runs_on_every_redirect_hop(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """A chain that only turns mutating on its third hop. Asserting on the final error
    alone would pass even if the guard ran once, so count the hops it actually saw."""
    seen: list[str] = []
    enforce = client._http._event_hooks["request"][0]

    async def spy(request: httpx.Request) -> None:
        seen.append(f"{request.method} {request.url.path}")
        await enforce(request)

    client._http._event_hooks["request"] = [spy]

    respx_mock.get("/api/2/entities/e1").mock(
        return_value=httpx.Response(302, headers={"Location": "/api/2/entities/e2"})
    )
    respx_mock.get("/api/2/entities/e2").mock(
        return_value=httpx.Response(302, headers={"Location": "/api/2/collections/42/reingest"})
    )
    blocked = respx_mock.post("/api/2/collections/42/reingest").mock(
        return_value=httpx.Response(200, json={})
    )

    with pytest.raises(ToolError, match="read-only"):
        await client.get_entity(entity_id="e1")

    assert seen == [
        "GET /api/2/entities/e1",
        "GET /api/2/entities/e2",
        "GET /api/2/collections/42/reingest",
    ]
    assert blocked.call_count == 0


async def test_307_redirect_cannot_replay_a_match_body_into_a_write(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """307 preserves method and body — the reason the host pin exists."""
    respx_mock.post("/api/2/match").mock(
        return_value=httpx.Response(307, headers={"Location": "/api/2/collections/42/ingest"})
    )
    blocked = respx_mock.post("/api/2/collections/42/ingest").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(ToolError, match="read-only"):
        await client.match_entity(
            sample={"schema": "Person", "properties": {"name": ["x"]}}, collection="874"
        )
    assert blocked.call_count == 0


async def test_cross_host_redirect_never_reaches_the_foreign_host(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """The foreign host is registered on the *same* router, so this fails if the guard
    stops firing. Verified by mutation: dropping the request hook makes the evil route
    receive one call.

    httpx also strips `Authorization` across a host change on its own, so the header
    assertion is defence in depth — what this server contributes is that the request is
    never issued at all.
    """
    respx_mock.get("/api/2/entities/e1").mock(
        return_value=httpx.Response(302, headers={"Location": "https://evil.example/steal"})
    )
    seen_auth: list[str | None] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={})

    evil = respx_mock.get("https://evil.example/steal").mock(side_effect=capture)
    with pytest.raises(ToolError, match="configured Aleph origin"):
        await client.get_entity(entity_id="e1")
    assert evil.call_count == 0
    assert seen_auth == []


# -- encoding -----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/2/entities/e1%00/../../collections/42/reingest",
        "/api/2/entities/..%2f..%2fcollections%2f42%2freingest",
        "/api/2/entities/e1%2F..%2F..%2Fcollections%2F42%2Freingest",
        "/api/2/entities/e1/%2e%2e/%2e%2e/collections/42/reingest",
        "/api/2/entities/e1;/../collections/42/reingest",
        "/api/2/entities//../collections/42/reingest",
    ],
)
async def test_encoded_traversal_cannot_reach_a_write(path: str) -> None:
    hook = read_only_hook("https://aleph.test")
    with pytest.raises(ReadOnlyViolation):
        await hook(httpx.Request("GET", f"https://aleph.test{path}"))


async def test_encoding_inside_an_allowlisted_path_is_allowed() -> None:
    """Decoding can only add separators, so it makes fullmatch stricter, never looser.
    `e%31` decodes to `e1` and addresses the same endpoint."""
    hook = read_only_hook("https://aleph.test")
    request = httpx.Request("GET", "https://aleph.test/api/2/entities/e%31")
    await hook(request)
    assert request.url.path == "/api/2/entities/e1"


def test_id_charset_excludes_percent() -> None:
    """Tripwire for the decoded-path match. If `%` is ever added to the accepted id
    charset, the guard must match `raw_path` instead — see specs/read-only-guard."""
    from aleph_mcp.client import _ENTITY_ID

    assert not _ENTITY_ID.fullmatch("a%2Fb")
    assert "%" not in _ENTITY_ID.pattern


# -- query surface ------------------------------------------------------------
#
# The allowlist matches (method, path) only; query strings are NOT part of it. The
# query surface is closed at construction instead: every parameter name is either a
# literal this server chose or a caller value confined behind a namespace prefix.

_LITERAL_PARAMS = frozenset(
    {
        "q",
        "limit",
        "offset",
        "facet",
        "highlight",
        "highlight_count",
        "refresh",
        "collection_ids",
        "sort",
    }
)
_NAMESPACES = ("filter:", "facet_size:", "facet_total:")
_HOSTILE = "refresh=true&sync=true"


async def _emitted_params(client: AlephClient, respx_mock: respx.MockRouter) -> list[list[str]]:
    """Drive every tool that takes a caller-controlled key with a hostile value."""
    from urllib.parse import parse_qsl, urlsplit

    names: list[list[str]] = []

    def spy(request: httpx.Request) -> httpx.Response:
        names.append([k for k, _ in parse_qsl(urlsplit(str(request.url)).query)])
        return httpx.Response(200, json={"total": 0, "results": [], "id": "1"})

    respx_mock.route(host="aleph.test").mock(side_effect=spy)

    # Numeric collection ids throughout: a foreign_id makes each of these drivers issue a
    # `/api/2/collections` lookup first, and the spy records one parameter list per request
    # — so the sweep would be checking the resolver's own request rather than the tool's.
    await client.search_entities(collection="874", filters={_HOSTILE: "x"}, q="a")
    await client.search_entities(collection="874", facets=[_HOSTILE])
    await client.search_entities(collection="874", filters={"countries": [_HOSTILE]})
    await client.list_collections(q=_HOSTILE)
    await client.expand_entity(entity_id="e1", properties=[_HOSTILE])
    await client.list_entitysets(collection="42", set_type=_HOSTILE)
    return names


async def test_no_caller_value_becomes_a_query_parameter_name(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    for params in await _emitted_params(client, respx_mock):
        for name in params:
            assert name in _LITERAL_PARAMS or name.startswith(_NAMESPACES), name


async def test_hostile_value_adds_no_extra_query_parameter(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """`&` and `=` inside a caller value must be percent-encoded within the name, not
    terminate it and start a second parameter."""
    for params in await _emitted_params(client, respx_mock):
        assert "refresh" not in params
        assert "sync" not in params


async def test_refresh_is_emitted_only_by_get_collection(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    """`refresh=true` asks Aleph to recompute statistics — the only request that asks
    the server to do work. Tripwire so the exception list cannot grow quietly. Both
    get_collection branches end on the same numeric route, so both refresh; nothing
    else may.

    Every other driver is given a numeric collection so no foreign-id lookup is issued:
    the resolver's own `/api/2/collections` request carries no `refresh`, but it would
    make this sweep's request list depend on the resolver cache rather than on the tools.
    """
    from urllib.parse import parse_qsl, urlsplit

    refreshing: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        query = dict(parse_qsl(urlsplit(str(request.url)).query))
        if "refresh" in query:
            refreshing.append(request.url.path)
        return httpx.Response(
            200, json={"total": 0, "results": [{"id": "42"}], "id": "42", "properties": {}}
        )

    respx_mock.route(host="aleph.test").mock(side_effect=spy)

    await client.list_collections()
    await client.get_collection(collection="42")
    await client.get_collection(collection="my-case")
    await client.search_entities(collection="874", q="x")
    await client.get_entity(entity_id="e1")
    await client.expand_entity(entity_id="e1")
    await client.entity_tags(entity_id="e1")
    await client.similar_entities(entity_id="e1")
    await client.list_entitysets(collection="42")
    await client.entityset_items(entityset_id="es1")
    await client.xref_results(collection="42")

    assert refreshing == ["/api/2/collections/42", "/api/2/collections/42"]
