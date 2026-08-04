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
        ("GET", "/api/2/entitysets"),
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


async def test_base_path_prefix_is_stripped_before_matching() -> None:
    hook = read_only_hook("https://aleph.test/aleph")
    await hook(httpx.Request("GET", "https://aleph.test/aleph/api/2/entities"))
    with pytest.raises(ReadOnlyViolation, match="read-only"):
        await hook(httpx.Request("POST", "https://aleph.test/aleph/api/2/entities"))
    with pytest.raises(ReadOnlyViolation, match="base path"):
        await hook(httpx.Request("GET", "https://aleph.test/api/2/entities"))


async def test_request_leaving_the_configured_host_is_blocked() -> None:
    hook = read_only_hook("https://aleph.test")
    with pytest.raises(ReadOnlyViolation, match="configured Aleph host"):
        await hook(httpx.Request("GET", "https://evil.example/api/2/entities"))


async def test_cross_host_redirect_is_blocked(
    client: AlephClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/api/2/entities/e1").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://evil.example/api/2/entities"}
        )
    )
    with pytest.raises(ToolError, match="configured Aleph host"):
        await client.get_entity(entity_id="e1")
