import httpx
import pytest
from fastmcp.exceptions import ResourceError, ToolError

from aleph_mcp.errors import raise_for_status


def _resp(status: int, text: str = "") -> httpx.Response:
    return httpx.Response(status, text=text, request=httpx.Request("GET", "https://aleph.test/x"))


def test_success_is_noop() -> None:
    raise_for_status(_resp(200), context="t")


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, "invalid or expired"),
        (403, "not authorised"),
        (404, "not found"),
        (400, "bad request"),
        (429, "rate limited"),
        (500, "unexpected HTTP 500"),
    ],
)
def test_status_messages(status: int, needle: str) -> None:
    with pytest.raises(ToolError, match=needle):
        raise_for_status(_resp(status, "body"), context="ctx")


def test_403_names_the_write_scope_trap() -> None:
    with pytest.raises(ToolError, match="WRITE/admin"):
        raise_for_status(_resp(403), context="ctx")


def test_resource_flag_selects_resource_error() -> None:
    with pytest.raises(ResourceError):
        raise_for_status(_resp(404), context="aleph://schema/Person", resource=True)


def test_body_is_truncated() -> None:
    with pytest.raises(ToolError) as exc:
        raise_for_status(_resp(400, "x" * 900), context="ctx")
    assert "…" in str(exc.value)
    assert len(str(exc.value)) < 700
