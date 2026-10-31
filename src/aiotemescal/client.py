"""Asyncio client for LG soundbars."""

import asyncio
from collections.abc import Callable
import logging
import socket
from types import TracebackType
from typing import Any, Self

from .const import (
    DEFAULT_PORT,
    MSG_EQ_VIEW_INFO,
    MSG_FUNC_VIEW_INFO,
    MSG_MAC_INFO_DEV,
    MSG_PLAY_INFO,
    MSG_PRODUCT_INFO,
    MSG_SETTING_VIEW_INFO,
    MSG_SPK_LIST_VIEW_INFO,
)
from .exceptions import (
    TemescalConnectionError,
    TemescalProtocolError,
    TemescalTimeoutError,
)
from .protocol import (
    FRAME_MARKER,
    LENGTH_SIZE,
    decode_body,
    decode_length,
    encode_frame,
)

_LOGGER = logging.getLogger(__package__)

# Real messages are a few KiB; anything bigger means the stream is out of sync
MAX_BODY_SIZE = 1 << 20

# A device that loses power stops acknowledging, so the kernel detects it without
# any application traffic: idle connections after 5 + 2 * 1 s of keepalive probes,
# and connections with unacknowledged data (a command just sent) after 3 s
_TCP_OPTIONS = (
    ("TCP_KEEPIDLE", 5),
    ("TCP_KEEPINTVL", 1),
    ("TCP_KEEPCNT", 2),
    ("TCP_USER_TIMEOUT", 3000),
)

type MessageCallback = Callable[[dict[str, Any]], None]
type ConnectionCallback = Callable[[bool], None]

_SESSION_ERRORS = (OSError, asyncio.IncompleteReadError, TemescalProtocolError)


class TemescalClient:
    """Connection to an LG soundbar.

    Use ``start()``/``stop()`` for a long-lived connection that survives the
    device going away, or ``async with`` for a single connection attempt.
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        response_timeout: float = 5.0,
        connect_timeout: float = 5.0,
        min_backoff: float = 1.0,
        max_backoff: float = 5.0,
    ) -> None:
        """Initialize the client; no I/O happens until start or connect."""
        self.host = host
        self.port = port
        self._response_timeout = response_timeout
        self._connect_timeout = connect_timeout
        self._min_backoff = min_backoff
        self._max_backoff = max_backoff
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._pending: dict[str, list[asyncio.Future[dict[str, Any]]]] = {}
        self._message_callbacks: list[MessageCallback] = []
        self._connection_callbacks: list[ConnectionCallback] = []

    @property
    def connected(self) -> bool:
        """Return whether the device is currently connected."""
        return self._writer is not None

    def subscribe(self, callback: MessageCallback) -> Callable[[], None]:
        """Call back with every message received; return an unsubscribe function."""
        return _register(self._message_callbacks, callback)

    def subscribe_connection(self, callback: ConnectionCallback) -> Callable[[], None]:
        """Call back with each connection state change; return an unsubscribe function."""
        return _register(self._connection_callbacks, callback)

    async def start(self) -> None:
        """Keep a connection to the device open in the background until stopped."""
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(), name=f"aiotemescal {self.host}"
            )

    def reconnect_now(self) -> None:
        """Retry connecting right away, e.g. when the device announces itself."""
        if self._writer is None:
            self._wake.set()

    def set_host(self, host: str) -> None:
        """Change the address of the device and connect to it right away."""
        self.host = host
        self.reconnect_now()

    async def connect(self) -> None:
        """Connect once, without reconnecting if the connection is lost."""
        await self._open()
        self._task = asyncio.create_task(
            self._serve_once(), name=f"aiotemescal {self.host}"
        )

    async def stop(self) -> None:
        """Close the connection and stop reconnecting."""
        if (task := self._task) is not None:
            self._task = None
            task.cancel()
            await asyncio.wait([task])
        self._close()

    async def __aenter__(self) -> Self:
        """Connect once."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Disconnect."""
        await self.stop()

    async def send(
        self, msg: str, data: dict[str, Any] | None = None, cmd: str = "get"
    ) -> None:
        """Send a message; answers are delivered to subscribers."""
        if (writer := self._writer) is None:
            raise TemescalConnectionError(f"Not connected to {self.host}")
        payload: dict[str, Any] = {"cmd": cmd, "msg": msg}
        if data is not None:
            payload["data"] = data
        _LOGGER.debug("%s: sending %s", self.host, payload)
        try:
            writer.write(encode_frame(payload))
            await writer.drain()
        except OSError as err:
            raise TemescalConnectionError(
                f"Cannot send to {self.host}: {err!r}"
            ) from err

    async def request(
        self, msg: str, data: dict[str, Any] | None = None, cmd: str = "get"
    ) -> dict[str, Any]:
        """Send a message and return the next message of the same type."""
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        futures = self._pending.setdefault(msg, [])
        futures.append(future)
        try:
            await self.send(msg, data, cmd)
            async with asyncio.timeout(self._response_timeout):
                return await future
        except TimeoutError as err:
            raise TemescalTimeoutError(f"No {msg} answer from {self.host}") from err
        finally:
            futures.remove(future)
            if not futures and self._pending.get(msg) is futures:
                del self._pending[msg]

    async def _run(self) -> None:
        backoff = self._min_backoff
        while True:
            self._wake.clear()
            try:
                await self._open()
            except TemescalConnectionError as err:
                _LOGGER.debug("%s, retrying in %.1f s", err, backoff)
                if await self._wait(backoff):
                    backoff = self._min_backoff
                else:
                    backoff = min(backoff * 2, self._max_backoff)
                continue
            backoff = self._min_backoff
            try:
                await self._read_frames()
            except _SESSION_ERRORS as err:
                _LOGGER.debug("%s: connection lost: %r", self.host, err)
            finally:
                self._close()
            await self._wait(backoff)

    async def _wait(self, delay: float) -> bool:
        """Sleep for the delay; return whether reconnect_now() cut it short."""
        try:
            async with asyncio.timeout(delay):
                await self._wake.wait()
        except TimeoutError:
            return False
        return True

    async def _serve_once(self) -> None:
        try:
            await self._read_frames()
        except _SESSION_ERRORS as err:
            _LOGGER.debug("%s: connection lost: %r", self.host, err)
        finally:
            self._close()

    async def _open(self) -> None:
        _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        try:
            async with asyncio.timeout(self._connect_timeout):
                reader, writer = await asyncio.open_connection(self.host, self.port)
        except OSError as err:
            raise TemescalConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err!r}"
            ) from err
        if (sock := writer.get_extra_info("socket")) is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for name, value in _TCP_OPTIONS:
                if (option := getattr(socket, name, None)) is not None:
                    sock.setsockopt(socket.IPPROTO_TCP, option, value)
        self._reader, self._writer = reader, writer
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)
        self._notify_connection(True)

    def _close(self) -> None:
        if (writer := self._writer) is None:
            return
        self._reader = self._writer = None
        # abort() rather than close(): a powered-off device never acknowledges
        writer.transport.abort()
        for futures in self._pending.values():
            for future in futures:
                if not future.done():
                    future.set_exception(
                        TemescalConnectionError(f"Connection to {self.host} lost")
                    )
        _LOGGER.debug("Disconnected from %s", self.host)
        self._notify_connection(False)

    async def _read_frames(self) -> None:
        if (reader := self._reader) is None:
            return
        while True:
            marker = (await reader.readexactly(1))[0]
            if marker != FRAME_MARKER:
                _LOGGER.debug("%s: skipping byte %#x", self.host, marker)
                continue
            length = decode_length(await reader.readexactly(LENGTH_SIZE))
            if length > MAX_BODY_SIZE:
                raise TemescalProtocolError(f"Frame too large: {length}")
            body = await reader.readexactly(length)
            try:
                message = decode_body(body)
            except TemescalProtocolError as err:
                _LOGGER.warning("%s: ignoring undecodable frame: %s", self.host, err)
                continue
            _LOGGER.debug("%s: received %s", self.host, message)
            self._dispatch(message)

    def _dispatch(self, message: dict[str, Any]) -> None:
        for future in self._pending.get(message.get("msg", ""), []):
            if not future.done():
                future.set_result(message)
        for callback in list(self._message_callbacks):
            try:
                callback(message)
            except Exception:
                _LOGGER.exception("%s: error in message callback", self.host)

    def _notify_connection(self, connected: bool) -> None:
        for callback in list(self._connection_callbacks):
            try:
                callback(connected)
            except Exception:
                _LOGGER.exception("%s: error in connection callback", self.host)

    async def get_eq(self) -> None:
        """Ask for the equaliser state."""
        await self.send(MSG_EQ_VIEW_INFO)

    async def get_info(self) -> None:
        """Ask for the speaker state (volume, mute, power, name)."""
        await self.send(MSG_SPK_LIST_VIEW_INFO)

    async def get_play(self) -> None:
        """Ask for the playback state."""
        await self.send(MSG_PLAY_INFO)

    async def get_func(self) -> None:
        """Ask for the current and available inputs."""
        await self.send(MSG_FUNC_VIEW_INFO)

    async def get_settings(self) -> None:
        """Ask for the settings."""
        await self.send(MSG_SETTING_VIEW_INFO)

    async def get_product_info(self) -> None:
        """Ask for the product information."""
        await self.send(MSG_PRODUCT_INFO)

    async def get_mac_info(self) -> None:
        """Ask for the network information."""
        await self.send(MSG_MAC_INFO_DEV)

    async def set_eq(self, eq: int) -> None:
        """Select an equaliser by index."""
        await self.send(MSG_EQ_VIEW_INFO, {"i_curr_eq": eq}, "set")

    async def set_func(self, func: int) -> None:
        """Select an input by index."""
        await self.send(MSG_FUNC_VIEW_INFO, {"i_curr_func": func}, "set")

    async def set_volume(self, volume: int) -> None:
        """Set the volume."""
        await self.send(MSG_SPK_LIST_VIEW_INFO, {"i_vol": volume}, "set")

    async def set_mute(self, mute: bool) -> None:
        """Mute or unmute."""
        await self.send(MSG_SPK_LIST_VIEW_INFO, {"b_mute": mute}, "set")

    async def set_power(self, on: bool) -> None:
        """Turn the device on or off (standby)."""
        await self.send(MSG_SPK_LIST_VIEW_INFO, {"b_powerkey": on}, "set")

    async def set_play_ctrl(self, play: bool) -> None:
        """Resume or pause playback."""
        await self.send(MSG_PLAY_INFO, {"i_play_ctrl": 0 if play else 1}, "set")

    async def set_setting(self, key: str, value: Any) -> None:
        """Change a SETTING_VIEW_INFO value such as b_night_mode or i_woofer_level."""
        await self.send(MSG_SETTING_VIEW_INFO, {key: value}, "set")


def _register[T](callbacks: list[T], callback: T) -> Callable[[], None]:
    callbacks.append(callback)

    def unregister() -> None:
        if callback in callbacks:
            callbacks.remove(callback)

    return unregister
