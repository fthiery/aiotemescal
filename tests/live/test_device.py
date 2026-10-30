"""Read-only tests against a real soundbar.

Nothing is changed on the device, but the heartbeat requests may light up its
front display. The power cycle test needs someone to unplug the device and is
only run when TEMESCAL_POWER_CYCLE is set.
"""

import asyncio
from collections import Counter
import os
import time

import pytest

from aiotemescal import (
    MSG_EQ_VIEW_INFO,
    MSG_FUNC_VIEW_INFO,
    MSG_PLAY_INFO,
    MSG_PRODUCT_INFO,
    MSG_SETTING_VIEW_INFO,
    MSG_SPK_LIST_VIEW_INFO,
    TemescalClient,
)

from .conftest import HOST, PORT

STATE_MESSAGES = (
    MSG_EQ_VIEW_INFO,
    MSG_FUNC_VIEW_INFO,
    MSG_PLAY_INFO,
    MSG_PRODUCT_INFO,
    MSG_SETTING_VIEW_INFO,
    MSG_SPK_LIST_VIEW_INFO,
)


async def wait_for_state(client: TemescalClient, connected: bool, timeout: float) -> float:
    """Wait for a connection state and return how long it took."""
    start = time.monotonic()
    async with asyncio.timeout(timeout):
        while client.connected is not connected:
            await asyncio.sleep(0.1)
    return time.monotonic() - start


async def test_identity(client: TemescalClient) -> None:
    """The device reports the name and model the integration relies on."""
    speaker = await client.request(MSG_SPK_LIST_VIEW_INFO)
    product = await client.request(MSG_PRODUCT_INFO)

    print(f"\nname={speaker['data']['s_user_name']!r}", product["data"])
    assert speaker["data"]["s_user_name"]
    assert product["data"]["s_model_name"]


@pytest.mark.parametrize("msg", STATE_MESSAGES)
async def test_state_messages_are_answered(client: TemescalClient, msg: str) -> None:
    """Every message the integration asks for on connection is answered."""
    answer = await client.request(msg)

    assert answer["msg"] == msg
    assert isinstance(answer.get("data"), dict)


async def test_volume_is_consistent(client: TemescalClient) -> None:
    data = (await client.request(MSG_SPK_LIST_VIEW_INFO))["data"]

    assert data["i_vol_min"] <= data["i_vol"] <= data["i_vol_max"]


async def test_heartbeat_keeps_the_connection() -> None:
    """An idle connection survives several heartbeats."""
    assert HOST
    interval = 3.0
    client = TemescalClient(HOST, PORT, heartbeat_interval=interval)
    received: Counter[str] = Counter()
    events: list[bool] = []
    client.subscribe(lambda message: received.update([message.get("msg", "")]))
    client.subscribe_connection(events.append)

    await client.start()
    try:
        await wait_for_state(client, True, 10)
        await asyncio.sleep(interval * 4)
        assert client.connected
    finally:
        await client.stop()

    assert events == [True, False]
    assert received[MSG_PRODUCT_INFO] >= 3


@pytest.mark.skipif(
    not os.environ.get("TEMESCAL_POWER_CYCLE"),
    reason="TEMESCAL_POWER_CYCLE is not set",
)
async def test_power_cycle() -> None:
    """Losing and regaining power is detected without restarting the client."""
    assert HOST
    client = TemescalClient(HOST, PORT)
    await client.start()
    try:
        await wait_for_state(client, True, 30)
        print("\n>>> Connected. Cut the power of the soundbar now.", flush=True)
        lost = await wait_for_state(client, False, 180)
        print(f">>> Loss detected after {lost:.0f} s. Power it back on.", flush=True)
        back = await wait_for_state(client, True, 300)
        print(f">>> Reconnected {back:.0f} s after the loss.", flush=True)
        answer = await client.request(MSG_SPK_LIST_VIEW_INFO)
    finally:
        await client.stop()

    assert answer["data"]["s_user_name"]
