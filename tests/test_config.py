import pytest
from pydantic import ValidationError

from aleph_mcp.config import Settings


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
