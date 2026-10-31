"""Tests for the temescal client against a fake soundbar."""

import asyncio
from collections.abc import AsyncGenerator, Callable
import socket

import pytest

from aiotemescal import TemescalClient, TemescalConnectionError, TemescalTimeoutError

from .conftest import FakeSoundbar, free_port

FAST = {
    "response_timeout": 0.2,
    "connect_timeout": 0.5,
    "min_backoff": 0.05,
    "max_backoff": 0.1,
}


async def wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    """Wait until the condition holds."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


@pytest.fixture
async def client(soundbar: FakeSoundbar) -> AsyncGenerator[TemescalClient]:
    """Return a started client connected to the fake soundbar."""
    client = TemescalClient("127.0.0.1", soundbar.port, **FAST)
    await client.start()
    await wait_for(lambda: client.connected)
    yield client
    await client.stop()


async def test_request(soundbar: FakeSoundbar, client: TemescalClient) -> None:
    soundbar.answers["SPK_LIST_VIEW_INFO"] = {"s_user_name": "Salon", "i_vol": 7}

    answer = await client.request("SPK_LIST_VIEW_INFO")

    assert answer == {
        "msg": "SPK_LIST_VIEW_INFO",
        "data": {"s_user_name": "Salon", "i_vol": 7},
    }


async def test_set_command(soundbar: FakeSoundbar, client: TemescalClient) -> None:
    await client.set_volume(12)

    assert await soundbar.received.get() == {
        "cmd": "set",
        "msg": "SPK_LIST_VIEW_INFO",
        "data": {"i_vol": 12},
    }


async def test_unsolicited_messages_reach_subscribers(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    messages: list[dict] = []
    unsubscribe = client.subscribe(messages.append)

    await soundbar.push({"msg": "PLAY_INFO", "data": {"i_play_ctrl": 1}})
    await wait_for(lambda: len(messages) == 1)
    unsubscribe()
    await soundbar.push({"msg": "PLAY_INFO", "data": {"i_play_ctrl": 0}})
    await asyncio.sleep(0.05)

    assert messages == [{"msg": "PLAY_INFO", "data": {"i_play_ctrl": 1}}]


async def test_failing_subscriber_does_not_break_the_connection(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    def broken(message: dict) -> None:
        raise RuntimeError("boom")

    client.subscribe(broken)

    await client.request("EQ_VIEW_INFO")
    await client.request("EQ_VIEW_INFO")
    assert client.connected


async def test_request_timeout(soundbar: FakeSoundbar, client: TemescalClient) -> None:
    soundbar.responsive = False

    with pytest.raises(TemescalTimeoutError):
        await client.request("MAC_INFO_DEV")


async def test_send_while_disconnected() -> None:
    client = TemescalClient("127.0.0.1", free_port(), **FAST)

    with pytest.raises(TemescalConnectionError):
        await client.get_info()


async def test_start_while_device_is_off() -> None:
    """The client keeps retrying until the device shows up."""
    soundbar = FakeSoundbar(free_port())
    client = TemescalClient("127.0.0.1", soundbar.port, **FAST)
    states: list[bool] = []
    client.subscribe_connection(states.append)

    await client.start()
    await asyncio.sleep(0.3)
    assert not client.connected
    assert states == []

    await soundbar.start()
    await wait_for(lambda: client.connected)
    assert states == [True]

    await client.stop()
    await soundbar.stop()
    assert states == [True, False]


async def test_reconnect_after_device_closes(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    states: list[bool] = []
    client.subscribe_connection(states.append)

    await soundbar.stop()
    await wait_for(lambda: not client.connected)
    await soundbar.start()
    await wait_for(lambda: client.connected)

    assert states == [False, True]


async def test_idle_connection_stays_quiet(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    """Liveness is left to TCP keepalive, so nothing is sent while idle."""
    states: list[bool] = []
    client.subscribe_connection(states.append)
    soundbar.responsive = False

    await asyncio.sleep(0.5)

    assert client.connected
    assert states == []
    assert soundbar.received.empty()
    assert soundbar.connection_count == 1


async def test_tcp_options(client: TemescalClient) -> None:
    """The kernel is set up to notice quickly that the device lost power."""
    assert client._writer is not None
    sock: socket.socket = client._writer.get_extra_info("socket")

    assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
    assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == 5
    assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL) == 1
    assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT) == 2
    assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == 3000


async def test_reconnect_now_skips_the_backoff() -> None:
    soundbar = FakeSoundbar(free_port())
    client = TemescalClient(
        "127.0.0.1", soundbar.port, **{**FAST, "min_backoff": 30, "max_backoff": 30}
    )
    await client.start()
    await asyncio.sleep(0.1)
    await soundbar.start()

    client.reconnect_now()
    await wait_for(lambda: client.connected, timeout=1)

    await client.stop()
    await soundbar.stop()


async def test_set_host_connects_to_the_new_address(soundbar: FakeSoundbar) -> None:
    client = TemescalClient(
        "127.0.0.2", soundbar.port, **{**FAST, "min_backoff": 30, "max_backoff": 30}
    )
    await client.start()
    await asyncio.sleep(0.1)
    assert not client.connected

    client.set_host("127.0.0.1")
    await wait_for(lambda: client.connected, timeout=1)

    assert client.host == "127.0.0.1"
    await client.stop()


async def test_pending_request_fails_on_disconnect(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    soundbar.responsive = False
    request = asyncio.create_task(client.request("PRODUCT_INFO"))
    await soundbar.received.get()

    await soundbar.stop()

    with pytest.raises(TemescalConnectionError):
        await request


async def test_one_shot_connection(soundbar: FakeSoundbar) -> None:
    soundbar.answers["PRODUCT_INFO"] = {"s_uuid": "abc"}

    async with TemescalClient("127.0.0.1", soundbar.port, **FAST) as client:
        answer = await client.request("PRODUCT_INFO")

    assert answer["data"] == {"s_uuid": "abc"}
    assert not client.connected


async def test_one_shot_connection_refused() -> None:
    with pytest.raises(TemescalConnectionError):
        async with TemescalClient("127.0.0.1", free_port(), **FAST):
            pass


async def test_stop_leaves_no_task(soundbar: FakeSoundbar) -> None:
    client = TemescalClient("127.0.0.1", soundbar.port, **FAST)
    await client.start()
    await wait_for(lambda: client.connected)

    await client.stop()
    await asyncio.sleep(0)

    assert not client.connected
    assert [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith("aiotemescal")
    ] == []
