"""Fake soundbar speaking the temescal protocol over TCP."""

import asyncio
from collections.abc import AsyncGenerator
import socket
from typing import Any

import pytest

from aiotemescal.protocol import LENGTH_SIZE, decode_body, decode_length, encode_frame


def free_port() -> int:
    """Return a TCP port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeSoundbar:
    """Answer every request with the configured data for its message type."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.answers: dict[str, dict[str, Any]] = {}
        # False makes the device ignore requests while keeping the connection open
        self.responsive = True
        # Message types the device never answers, like MAC_INFO_DEV on the SP8YA
        self.ignored: set[str] = set()
        self.received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)

    async def stop(self) -> None:
        """Stop listening and drop every connection."""
        if self._server is not None:
            self._server.close()
            self._server = None
        for writer in self._writers:
            writer.transport.abort()
        self._writers.clear()

    @property
    def connection_count(self) -> int:
        return len([w for w in self._writers if not w.transport.is_closing()])

    async def push(self, message: dict[str, Any]) -> None:
        """Send an unsolicited message to every client."""
        await self.push_raw(encode_frame(message))

    async def push_raw(self, data: bytes) -> None:
        """Send bytes as they are to every client."""
        for writer in self._writers:
            writer.write(data)
            await writer.drain()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.append(writer)
        try:
            while True:
                await reader.readexactly(1)
                length = decode_length(await reader.readexactly(LENGTH_SIZE))
                message = decode_body(await reader.readexactly(length))
                await self.received.put(message)
                if self.responsive and message["msg"] not in self.ignored:
                    answer = {"msg": message["msg"]}
                    if (data := self.answers.get(message["msg"])) is not None:
                        answer["data"] = data
                    writer.write(encode_frame(answer))
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass


@pytest.fixture
async def soundbar() -> AsyncGenerator[FakeSoundbar]:
    """Return a running fake soundbar."""
    bar = FakeSoundbar(free_port())
    await bar.start()
    yield bar
    await bar.stop()
