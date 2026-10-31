"""Watch a soundbar: python -m aiotemescal HOST."""

import argparse
import asyncio
import contextlib
import logging
from typing import Any

from . import DEFAULT_PORT, TemescalClient, TemescalConnectionError


async def _refresh(client: TemescalClient) -> None:
    with contextlib.suppress(TemescalConnectionError):
        for get in (
            client.get_product_info,
            client.get_info,
            client.get_func,
            client.get_eq,
            client.get_settings,
            client.get_play,
        ):
            await get()


async def _main(args: argparse.Namespace) -> None:
    client = TemescalClient(args.host, args.port)
    refreshes: set[asyncio.Task[None]] = set()

    def on_message(message: dict[str, Any]) -> None:
        print(f"<- {message}", flush=True)

    def on_connection(connected: bool) -> None:
        print("== connected" if connected else "== disconnected", flush=True)
        if connected:
            task = asyncio.create_task(_refresh(client))
            refreshes.add(task)
            task.add_done_callback(refreshes.discard)

    client.subscribe(on_message)
    client.subscribe_connection(on_connection)
    await client.start()
    try:
        await asyncio.Event().wait()
    finally:
        await client.stop()


def main() -> None:
    """Run the command line tool."""
    parser = argparse.ArgumentParser(prog="aiotemescal", description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logs")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main(args))


if __name__ == "__main__":
    main()
