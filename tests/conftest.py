from collections.abc import AsyncIterator, Iterator

import pytest
import respx

from aleph_mcp.client import AlephClient
from aleph_mcp.config import Settings

HOST = "https://aleph.test"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("ALEPHCLIENT_HOST", HOST)
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "test_key")
    monkeypatch.delenv("ALEPH_MCP_MAX_RETRIES", raising=False)
    return Settings()  # type: ignore[call-arg]


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=HOST, assert_all_called=False) as m:
        yield m


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AlephClient]:
    c = AlephClient(settings)
    yield c
    await c.aclose()
