"""Watch a soundbar: python -m aiotemescal HOST."""

import argparse
import asyncio
import contextlib
import logging
from typing import Any

from . import DEFAULT_PORT, TemescalClient


async def _main(args: argparse.Namespace) -> None:
    client = TemescalClient(args.host, args.port)

    def on_message(message: dict[str, Any]) -> None:
        print(f"<- {message}", flush=True)

    def on_connection(connected: bool) -> None:
        # The state the client requests on connection is printed just before
        print("== connected" if connected else "== disconnected", flush=True)

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
