"""Tests for the temescal client against a fake soundbar."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
import socket
from typing import Any
from unittest.mock import patch

import pytest

from aiotemescal import TemescalClient, TemescalConnectionError, TemescalTimeoutError
from aiotemescal.client import STATE_MESSAGES, _unacknowledged

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
    # Leave out the state requests sent when connecting
    while not soundbar.received.empty():
        soundbar.received.get_nowait()
    yield client
    await client.stop()


async def test_request(soundbar: FakeSoundbar, client: TemescalClient) -> None:
    soundbar.answers["SPK_LIST_VIEW_INFO"] = {"s_user_name": "Salon", "i_vol": 7}

    answer = await client.request("SPK_LIST_VIEW_INFO")

    assert answer == {
        "msg": "SPK_LIST_VIEW_INFO",
        "data": {"s_user_name": "Salon", "i_vol": 7},
    }


@pytest.mark.parametrize(
    ("action", "sent"),
    [
        pytest.param(
            lambda client: client.set_volume(12),
            {"cmd": "set", "msg": "SPK_LIST_VIEW_INFO", "data": {"i_vol": 12}},
            id="set_volume",
        ),
        pytest.param(
            lambda client: client.set_mute(True),
            {"cmd": "set", "msg": "SPK_LIST_VIEW_INFO", "data": {"b_mute": True}},
            id="set_mute",
        ),
        pytest.param(
            lambda client: client.set_power(False),
            {"cmd": "set", "msg": "SPK_LIST_VIEW_INFO", "data": {"b_powerkey": False}},
            id="set_power",
        ),
        pytest.param(
            lambda client: client.set_eq(19),
            {"cmd": "set", "msg": "EQ_VIEW_INFO", "data": {"i_curr_eq": 19}},
            id="set_eq",
        ),
        pytest.param(
            lambda client: client.set_func(6),
            {"cmd": "set", "msg": "FUNC_VIEW_INFO", "data": {"i_curr_func": 6}},
            id="set_func",
        ),
        pytest.param(
            lambda client: client.set_play_ctrl(True),
            {"cmd": "set", "msg": "PLAY_INFO", "data": {"i_play_ctrl": 0}},
            id="set_play_ctrl_play",
        ),
        pytest.param(
            lambda client: client.set_play_ctrl(False),
            {"cmd": "set", "msg": "PLAY_INFO", "data": {"i_play_ctrl": 1}},
            id="set_play_ctrl_pause",
        ),
        pytest.param(
            lambda client: client.set_setting("b_night_time", True),
            {"cmd": "set", "msg": "SETTING_VIEW_INFO", "data": {"b_night_time": True}},
            id="set_setting",
        ),
        pytest.param(
            lambda client: client.get_eq(),
            {"cmd": "get", "msg": "EQ_VIEW_INFO"},
            id="get_eq",
        ),
        pytest.param(
            lambda client: client.get_info(),
            {"cmd": "get", "msg": "SPK_LIST_VIEW_INFO"},
            id="get_info",
        ),
        pytest.param(
            lambda client: client.get_play(),
            {"cmd": "get", "msg": "PLAY_INFO"},
            id="get_play",
        ),
        pytest.param(
            lambda client: client.get_func(),
            {"cmd": "get", "msg": "FUNC_VIEW_INFO"},
            id="get_func",
        ),
        pytest.param(
            lambda client: client.get_settings(),
            {"cmd": "get", "msg": "SETTING_VIEW_INFO"},
            id="get_settings",
        ),
        pytest.param(
            lambda client: client.get_product_info(),
            {"cmd": "get", "msg": "PRODUCT_INFO"},
            id="get_product_info",
        ),
        pytest.param(
            lambda client: client.get_mac_info(),
            {"cmd": "get", "msg": "MAC_INFO_DEV"},
            id="get_mac_info",
        ),
    ],
)
async def test_command(
    soundbar: FakeSoundbar,
    client: TemescalClient,
    action: Callable[[TemescalClient], Awaitable[None]],
    sent: dict[str, Any],
) -> None:
    """Each action sends the message the device expects."""
    await action(client)

    assert await soundbar.received.get() == sent


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


async def test_connection_reported_once_state_is_answered(
    soundbar: FakeSoundbar,
) -> None:
    """Subscribers get the fresh state before the connection is reported."""
    soundbar.answers["SPK_LIST_VIEW_INFO"] = {"i_vol": 7}
    client = TemescalClient("127.0.0.1", soundbar.port, **FAST)
    events: list[Any] = []
    client.subscribe(lambda message: events.append(message["msg"]))
    client.subscribe_connection(events.append)

    await client.start()
    await wait_for(lambda: client.connected)

    assert sorted(events[:-1]) == sorted(STATE_MESSAGES)
    assert events[-1] is True
    assert sorted(
        soundbar.received.get_nowait()["msg"] for _ in STATE_MESSAGES
    ) == sorted(STATE_MESSAGES)
    await client.stop()


async def test_unanswered_state_requests_time_out(soundbar: FakeSoundbar) -> None:
    """A device that ignores the state requests is reported after the timeout."""
    soundbar.responsive = False
    client = TemescalClient("127.0.0.1", soundbar.port, **FAST)

    await client.start()
    await wait_for(lambda: soundbar.connection_count == 1)
    assert not client.connected

    await wait_for(lambda: client.connected, timeout=1)
    await client.stop()


async def test_connection_lost_before_state_is_answered(
    soundbar: FakeSoundbar,
) -> None:
    """A connection lost while requesting the state is never reported."""
    soundbar.responsive = False
    client = TemescalClient(
        "127.0.0.1", soundbar.port, **{**FAST, "response_timeout": 5}
    )
    states: list[bool] = []
    client.subscribe_connection(states.append)

    await client.start()
    await soundbar.received.get()
    await soundbar.stop()
    await asyncio.sleep(0.2)

    assert states == []
    assert not client.connected
    await client.stop()


async def test_command_waits_for_acknowledgement(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    """A command returns once the device acknowledged every byte sent."""
    with patch(
        "aiotemescal.client._unacknowledged", side_effect=[64, 64, 0]
    ) as unacknowledged:
        await client.set_volume(12)

    assert unacknowledged.call_count == 3


async def test_unacknowledged_command_times_out(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    """A command the device never acknowledges fails instead of being lost."""
    with (
        patch("aiotemescal.client._unacknowledged", return_value=64),
        pytest.raises(TemescalTimeoutError),
    ):
        await client.set_volume(12)


async def test_connection_lost_before_acknowledgement(soundbar: FakeSoundbar) -> None:
    """A connection lost while waiting for the acknowledgement fails the command."""
    client = TemescalClient(
        "127.0.0.1", soundbar.port, **{**FAST, "response_timeout": 5}
    )
    await client.start()
    await wait_for(lambda: client.connected)

    with patch("aiotemescal.client._unacknowledged", return_value=64):
        command = asyncio.create_task(client.set_volume(12))
        await asyncio.sleep(0.05)
        await soundbar.stop()
        with pytest.raises(TemescalConnectionError) as err:
            await command

    assert err.type is TemescalConnectionError
    await client.stop()


async def test_idle_socket_has_nothing_unacknowledged(
    soundbar: FakeSoundbar, client: TemescalClient
) -> None:
    """The kernel reports everything sent as acknowledged once answered."""
    await client.request("EQ_VIEW_INFO")
    assert client._writer is not None

    assert _unacknowledged(client._writer.get_extra_info("socket")) == 0
