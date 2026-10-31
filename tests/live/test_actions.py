"""Tests that change settings of a real soundbar and restore them.

Every change is undone at the end of its test and checked to be reported back.
The changes can be heard or seen on the device, so these tests only run when
TEMESCAL_ACTIONS is set.
"""

import asyncio
from collections.abc import Awaitable, Callable
import os
from typing import Any

import pytest

from aiotemescal import (
    MSG_EQ_VIEW_INFO,
    MSG_FUNC_VIEW_INFO,
    MSG_PLAY_INFO,
    MSG_SETTING_VIEW_INFO,
    MSG_SPK_LIST_VIEW_INFO,
    TemescalClient,
    functions,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEMESCAL_ACTIONS"), reason="TEMESCAL_ACTIONS is not set"
)

STATE_MESSAGES = (
    MSG_EQ_VIEW_INFO,
    MSG_FUNC_VIEW_INFO,
    MSG_PLAY_INFO,
    MSG_SETTING_VIEW_INFO,
    MSG_SPK_LIST_VIEW_INFO,
)
# Switching to these resumes whatever was last streamed, at its own volume
STREAMING_INPUTS = {
    functions.index(name) for name in ("Wi-Fi", "Bluetooth", "Spotify", "Chromecast")
}

# Selecting "Optical/HDMI ARC" makes the device report "Optical"
REPORTED_INPUTS = {functions.index("Optical/HDMI ARC"): functions.index("Optical")}

type State = dict[str, dict[str, Any]]
type Setter = Callable[[TemescalClient, Any], Awaitable[None]]


@pytest.fixture
async def state(client: TemescalClient) -> State:
    """Return every value the device reports before the test."""
    return {msg: (await client.request(msg))["data"] for msg in STATE_MESSAGES}


async def wait_for_value(
    client: TemescalClient, msg: str, key: str, value: Any
) -> None:
    """Wait until a request reports the value.

    Requests sent right after a change still return the previous value.
    """
    async with asyncio.timeout(10):
        while (await client.request(msg))["data"][key] != value:
            await asyncio.sleep(0.5)


async def set_and_wait(
    client: TemescalClient,
    setter: Setter,
    value: Any,
    msg: str,
    key: str,
    reported: Any = None,
) -> None:
    """Apply a value and wait for the device to report it.

    The device confirms with a notibyset message; an input switch first
    reports the previous input, so only the expected value counts.
    """
    expected = value if reported is None else reported
    done = asyncio.Event()

    def on_message(message: dict[str, Any]) -> None:
        if message["msg"] == msg and (message.get("data") or {}).get(key) == expected:
            done.set()

    unsubscribe = client.subscribe(on_message)
    try:
        await setter(client, value)
        async with asyncio.timeout(10):
            await done.wait()
    finally:
        unsubscribe()


def other_in_list(
    list_key: str,
    current_key: str,
    avoid: set[int] | None = None,
    reported: dict[int, int] | None = None,
) -> Callable[[State, str], Any]:
    """Pick another value offered by the device in a list.

    A value the device reports as the current one would change nothing.
    """

    def pick(state: State, msg: str) -> Any:
        current = state[msg][current_key]
        candidates = [
            value
            for value in state[msg][list_key]
            if (reported or {}).get(value, value) != current
            and value not in (avoid or set())
        ]
        if not candidates:
            pytest.skip(f"No other {current_key} to switch to")
        return candidates[0]

    return pick


def neighbour_level(level_key: str, min_key: str) -> Callable[[State, str], Any]:
    """Pick the level next to the current one, staying within range."""

    def pick(state: State, msg: str) -> Any:
        level = state[msg][level_key]
        return level - 1 if level > state[msg][min_key] else level + 1

    return pick


def as_requested(value: Any) -> Any:
    """Return the value the device reports for a requested one."""
    return value


def toggled(key: str) -> Callable[[State, str], Any]:
    """Pick the opposite of a boolean."""
    return lambda state, msg: not state[msg][key]


async def test_play_control(client: TemescalClient, state: State) -> None:
    """Pausing or resuming a stream is reported back, then undone."""
    if state[MSG_PLAY_INFO]["i_stream_type"] == 0:
        pytest.skip("Nothing is streaming, the device ignores play control")
    original = state[MSG_PLAY_INFO]["i_play_ctrl"]

    # The device reports 0 when playing and 1 when paused
    def setter(client: TemescalClient, value: int) -> Awaitable[None]:
        return client.set_play_ctrl(value == 0)

    try:
        await set_and_wait(client, setter, 1 - original, MSG_PLAY_INFO, "i_play_ctrl")
    finally:
        await set_and_wait(client, setter, original, MSG_PLAY_INFO, "i_play_ctrl")


@pytest.mark.parametrize(
    ("msg", "key", "setter", "pick", "reported"),
    [
        pytest.param(
            MSG_SPK_LIST_VIEW_INFO,
            "i_vol",
            TemescalClient.set_volume,
            lambda state, msg: (
                state[msg]["i_vol"] + 1
                if state[msg]["i_vol"] < state[msg]["i_vol_max"]
                else state[msg]["i_vol"] - 1
            ),
            as_requested,
            id="volume",
        ),
        pytest.param(
            MSG_SPK_LIST_VIEW_INFO,
            "b_mute",
            TemescalClient.set_mute,
            toggled("b_mute"),
            as_requested,
            id="mute",
        ),
        pytest.param(
            MSG_EQ_VIEW_INFO,
            "i_curr_eq",
            TemescalClient.set_eq,
            other_in_list("ai_eq_list", "i_curr_eq"),
            as_requested,
            id="equaliser",
        ),
        pytest.param(
            MSG_FUNC_VIEW_INFO,
            "i_curr_func",
            TemescalClient.set_func,
            other_in_list(
                "ai_func_list", "i_curr_func", STREAMING_INPUTS, REPORTED_INPUTS
            ),
            lambda value: REPORTED_INPUTS.get(value, value),
            id="input",
        ),
        pytest.param(
            MSG_SETTING_VIEW_INFO,
            "b_night_time",
            lambda client, value: client.set_setting("b_night_time", value),
            toggled("b_night_time"),
            as_requested,
            id="night_mode",
        ),
        pytest.param(
            MSG_SETTING_VIEW_INFO,
            "i_rear_level",
            lambda client, value: client.set_setting("i_rear_level", value),
            neighbour_level("i_rear_level", "i_rear_min"),
            as_requested,
            id="rear_level",
        ),
    ],
)
async def test_change_and_restore(
    client: TemescalClient,
    state: State,
    msg: str,
    key: str,
    setter: Setter,
    pick: Callable[[State, str], Any],
    reported: Callable[[Any], Any],
) -> None:
    """A change is applied, reported back, and undone."""
    original = state[msg][key]
    changed = pick(state, msg)

    try:
        await set_and_wait(client, setter, changed, msg, key, reported(changed))
        await wait_for_value(client, msg, key, reported(changed))
    finally:
        await set_and_wait(client, setter, original, msg, key)
    await wait_for_value(client, msg, key, original)


async def test_power_off_and_on(client: TemescalClient) -> None:
    """The device stays reachable through standby.

    The device reports neither its power state nor an answer to the power key,
    so whether it actually turned off and on can only be seen on it. It must
    be on before the test, which leaves it on.
    """
    await client.set_power(False)
    await asyncio.sleep(10)
    assert (await client.request(MSG_SPK_LIST_VIEW_INFO))["data"]["s_user_name"]

    await client.set_power(True)
    await asyncio.sleep(10)
    assert client.connected
