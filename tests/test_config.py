import pytest
from pydantic import ValidationError

from aleph_mcp.config import KEYCHAIN_MISS, Settings


def test_required_fields_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ALEPHCLIENT_HOST", "ALEPHCLIENT_API_KEY", "ALEPH_MCP_HOST", "ALEPH_MCP_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_host_trailing_slash_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://aleph.test/")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "k")
    assert Settings().host == "https://aleph.test"  # type: ignore[call-arg]


@pytest.mark.parametrize("suffix", ["/api/2", "/api/2/", "/api"])
def test_host_api_suffix_stripped(monkeypatch: pytest.MonkeyPatch, suffix: str) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", f"https://aleph.test{suffix}")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "k")
    assert Settings().host == "https://aleph.test"  # type: ignore[call-arg]


def test_host_without_scheme_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", "aleph.test")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "k")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_aleph_mcp_prefixed_aliases_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALEPHCLIENT_HOST", raising=False)
    monkeypatch.delenv("ALEPHCLIENT_API_KEY", raising=False)
    monkeypatch.setenv("ALEPH_MCP_HOST", "https://other.test")
    monkeypatch.setenv("ALEPH_MCP_API_KEY", "k2")
    s = Settings()  # type: ignore[call-arg]
    assert (s.host, s.api_key.get_secret_value()) == ("https://other.test", "k2")


def test_the_keychain_miss_marker_is_refused_and_names_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin emits this marker when the login Keychain holds no entry for the host it
    was pointed at. Starting anyway would mean a `.env` in the working directory could aim
    the client at an origin of its choosing while a real key was still attached."""
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://evil.example")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", KEYCHAIN_MISS)
    with pytest.raises(ValidationError, match=r"no Keychain entry for https://evil\.example"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "whitespace"])
def test_a_blank_key_is_refused_at_startup(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Otherwise it is a 401 on the first tool call, attributed to the wrong thing."""
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://aleph.test")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", value)
    with pytest.raises(ValidationError, match="api_key is empty"):
        Settings()  # type: ignore[call-arg]
