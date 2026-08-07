from __future__ import annotations

import asyncio
import sys

from pydantic import ValidationError

from .config import Settings
from .server import build_server


async def _serve(settings: Settings) -> None:
    mcp, client = build_server(settings)
    try:
        await mcp.run_async()
    finally:
        await client.aclose()


def main() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as e:
        print(f"aleph-mcp: configuration error: {e.errors(include_input=False)}", file=sys.stderr)
        print(
            "aleph-mcp: set ALEPHCLIENT_HOST and ALEPHCLIENT_API_KEY (use a READ-only Aleph role).",
            file=sys.stderr,
        )
        sys.exit(2)
    asyncio.run(_serve(settings))


if __name__ == "__main__":
    main()
