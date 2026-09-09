import asyncio
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

# Named so a test can assert the route was *not* used. This matters because respx matches in
# registration order and the fixture registers first, so a catch-all a test builds later
# never sees /api/2/metadata -- which silently emptied the "a refused call costs no request"
# assertions of their strongest case. Measured with the fetch moved ahead of the endpoint's
# own request, the invariant `_reply`'s docstring states: 57 tests red without this route, 1
# with it. `assert_model_not_fetched` is what puts that coverage back.
METADATA_ROUTE = "metadata"


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=HOST, assert_all_called=False) as m:
        m.get("/api/2/metadata", name=METADATA_ROUTE).mock(
            return_value=httpx.Response(200, json=DEFAULT_MODEL)
        )
        yield m


def assert_model_not_fetched(router: respx.MockRouter) -> None:
    """The instance-model fetch is an upstream request like any other.

    Paired with a catch-all's `call_count == 0` wherever a call is refused: the seam fetches
    the model inside `_reply`, after the endpoint has issued its own request, so a call
    refused before that point must not have reached this route either.
    """
    assert not router[METADATA_ROUTE].called, (
        "the instance model was fetched on a call that was refused. The seam must fetch it "
        "only after the endpoint has made its own request, or a refusal starts costing an "
        "upstream request -- see _reply's docstring."
    )


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the retry path without paying its backoff in wall-clock time.

    Patched on the `asyncio` module rather than through the module under test. The retry
    sleep moved from `client.py` to `transport.py`, and both spellings reach the same
    function object anyway -- `aleph_mcp.client.asyncio` *is* `asyncio` -- so naming the
    module directly is the spelling that cannot go stale when the caller moves again. It
    is also what the two budget tests that patch `asyncio.sleep` inline already do.
    """

    async def _sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AlephClient]:
    c = AlephClient(settings)
    yield c
    await c.aclose()
