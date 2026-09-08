from collections.abc import AsyncIterator, Iterator

import httpx
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


# Every entity-returning method fetches the instance model through the shaping seam, so a
# real instance answers this route on every one of those calls. Answered here by default so
# that a test which says nothing about the ontology is not silently relying on the route
# being unmocked -- the model reaching the slimmer is what SHAPING_CASES pins, and what a
# test leaves unsaid should be "an instance that answers", not "an instance that does not".
# An empty `schemata` is deliberate: `derive_caption` treats it exactly as it treats no
# model at all, so this changes no caption any existing test asserts. Registering the same
# pattern again replaces this route, which is how the metadata-failure tests override it.
DEFAULT_MODEL = {"model": {"schemata": {}}}


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=HOST, assert_all_called=False) as m:
        m.get("/api/2/metadata").mock(return_value=httpx.Response(200, json=DEFAULT_MODEL))
        yield m


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AlephClient]:
    c = AlephClient(settings)
    yield c
    await c.aclose()
