"""Tests for the device report."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from aiotemescal import TemescalClient
from aiotemescal.__main__ import main
from aiotemescal.report import (
    REDACTED,
    TRANSITION_ASKED,
    TRANSITION_NOT_PUSHED,
    TRANSITION_NOT_REPORTED,
    TRANSITION_PUSHED,
    TRANSITION_SKIPPED,
    REPORT_MESSAGES,
    Report,
    Snapshot,
    analyse,
    collect,
    diff,
    gather,
    redact,
    render,
)

from .conftest import FakeSoundbar

# Shortened from what the SP8YA reported when on, then in network standby
ON: Snapshot = {
    "FUNC_VIEW_INFO": {
        "ai_func_list": [0, 1, 15, 6, 19],
        "b_connect": True,
        "i_curr_func": 20,
        "s_spk_bt_name": "Salle TV",
    },
    "SPK_LIST_VIEW_INFO": {"i_vol": 15, "i_curr_func": 20, "s_user_name": "Salle TV"},
    "EQ_VIEW_INFO": {"ai_eq_list": [19, 0, 24], "i_curr_eq": 0},
    "PRODUCT_INFO": {"s_model_name": "SP8YA"},
    "UPDATE_VIEW_INFO": {
        "o_system_ver": {
            "s_main": "2407090",
            "s_micom": "2207202",
            "s_c4a": "1.56.310669",
        }
    },
    "SETTING_VIEW_INFO": {
        "b_auto_power": True,
        "s_ipv4_addr": "192.168.1.127",
        "s_ipv6_addr": "2a01:e0a:11f1:33e0:f0d3:8069:8790:f64a",
    },
    "MAC_INFO_DEV": None,
}
STANDBY: Snapshot = {
    **ON,
    "FUNC_VIEW_INFO": {**ON["FUNC_VIEW_INFO"], "b_connect": False, "i_curr_func": 4},  # type: ignore[dict-item]
    "SPK_LIST_VIEW_INFO": {**ON["SPK_LIST_VIEW_INFO"], "i_curr_func": 4},  # type: ignore[dict-item]
}
IDENTIFYING = ("Salle TV", "192.168.1.127", "2a01:e0a", "64:cb:e9:fe:33:80")


async def test_collect(soundbar: FakeSoundbar) -> None:
    """Every message is asked for, and unanswered ones are reported as None."""
    soundbar.answers["PRODUCT_INFO"] = {"s_model_name": "SP8YA"}
    soundbar.ignored.add("MAC_INFO_DEV")

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        snapshot = await collect(client)

    assert list(snapshot) == list(REPORT_MESSAGES)
    assert snapshot["PRODUCT_INFO"] == {"s_model_name": "SP8YA"}
    assert snapshot["MAC_INFO_DEV"] is None
    assert snapshot["PLAY_INFO"] == {}


def test_analyse() -> None:
    """The findings name what matters for supporting the device."""
    findings = analyse(ON)

    assert "Model: SP8YA" in findings
    assert (
        "Firmware (main / micom / Chromecast): 2407090 / 2207202 / 1.56.310669"
        in findings
    )
    assert any(f.startswith("Power state: not reported") for f in findings)
    assert "Unique id: not reported (no `s_uuid`)" in findings
    assert "Sound modes without a name in aiotemescal: 24" in findings
    assert "Current input: 20 (E-ARC)" in findings
    assert "No answer to: `MAC_INFO_DEV`" in findings


def test_analyse_power_state_reported() -> None:
    """A device that reports b_powerstatus is recognised."""
    findings = analyse({"SPK_LIST_VIEW_INFO": {"b_powerstatus": True}})

    assert "Power state: reported (`b_powerstatus`)" in findings
    assert "Model: not reported" in findings
    assert "Firmware: not reported" in findings


def test_diff() -> None:
    """Only the fields that change between on and standby are listed."""
    assert diff(ON, STANDBY) == [
        ("FUNC_VIEW_INFO", "b_connect", True, False),
        ("FUNC_VIEW_INFO", "i_curr_func", 20, 4),
        ("SPK_LIST_VIEW_INFO", "i_curr_func", 20, 4),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param({"s_user_name": "Salle TV"}, {"s_user_name": REDACTED}, id="name"),
        pytest.param(
            {"s_ipv4_addr": "10.0.0.2"}, {"s_ipv4_addr": REDACTED}, id="ip_key"
        ),
        pytest.param({"s_uuid": "abc"}, {"s_uuid": REDACTED}, id="uuid_key"),
        pytest.param({"s_user_name": ""}, {"s_user_name": ""}, id="empty_kept"),
        pytest.param(
            {"x": "mac 64:cb:e9:fe:33:80"}, {"x": f"mac {REDACTED}"}, id="mac"
        ),
        pytest.param(
            {"x": ["6ae736a7-1111-2222-3333-444455556666"]},
            {"x": [REDACTED]},
            id="uuid",
        ),
        pytest.param({"x": "at 192.168.1.127"}, {"x": f"at {REDACTED}"}, id="ipv4"),
        pytest.param({"x": "fe80::1:2:3"}, {"x": REDACTED}, id="ipv6"),
        pytest.param(
            {"s_c4a": "1.56.310669"}, {"s_c4a": "1.56.310669"}, id="version_kept"
        ),
        pytest.param(
            {"s_model_name": "SP8YA"}, {"s_model_name": "SP8YA"}, id="model_kept"
        ),
    ],
)
def test_redact(value: object, expected: object) -> None:
    """Addresses, identifiers and names are hidden, and nothing else."""
    assert redact(value) == expected


def test_render_redacted() -> None:
    """The report has the findings and the on/standby table, without identifying data."""
    report = Report(
        snapshot=ON,
        on=ON,
        standby=STANDBY,
        power_answers={"Did `set_power(False)` put it in standby?": "no"},
        timeline=[(1.5, "`FUNC_VIEW_INFO`", {"s_spk_bt_name": "Salle TV"})],
    )

    text = render(report)

    assert "- Model: SP8YA" in text
    assert "| `FUNC_VIEW_INFO` | `b_connect` | `True` | `False` |" in text
    assert "Did `set_power(False)` put it in standby? **no**" in text
    assert "# standby" in text
    for value in IDENTIFYING:
        assert value not in text


def test_render_not_redacted() -> None:
    """--no-redact keeps the names and addresses."""
    assert "192.168.1.127" in render(Report(snapshot=ON), redacted=False)


def test_render_standby_lost() -> None:
    """A device that leaves the network in standby is reported as such."""
    text = render(Report(snapshot=ON, on=ON, standby=None))

    assert "The connection was lost in standby" in text


async def test_gather(soundbar: FakeSoundbar) -> None:
    """Each power change says whether the device reported it, and how."""
    soundbar.answers["SPK_LIST_VIEW_INFO"] = {"b_powerstatus": True}
    answers = iter(["", "y", "", "y", "n", "", "", "y"])

    async def ask(prompt: str) -> str:
        if "standby with its remote" in prompt:
            # Reported by itself
            soundbar.answers["SPK_LIST_VIEW_INFO"] = {"b_powerstatus": False}
            await soundbar.push(
                {
                    "cmd": "notibyset",
                    "msg": "SPK_LIST_VIEW_INFO",
                    "data": {"b_powerstatus": False},
                }
            )
            # The user presses Enter once the device has changed
            await asyncio.sleep(0.1)
        elif "on with its remote" in prompt:
            # Only reported when asked
            soundbar.answers["SPK_LIST_VIEW_INFO"] = {"b_powerstatus": True}
        elif "the way you usually do" in prompt:
            # Not reported at all, but another field changes
            soundbar.answers["FUNC_VIEW_INFO"] = {"b_connect": False}
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0)

    assert report.transitions == [
        ("Standby with the remote", TRANSITION_PUSHED),
        ("On with the remote", TRANSITION_ASKED),
        ("`set_power(False)`", TRANSITION_NOT_PUSHED),
        ("`set_power(True)`", TRANSITION_NOT_PUSHED),
        ("Standby the usual way", TRANSITION_NOT_REPORTED),
    ]
    assert list(report.power_answers.values()) == ["yes", "yes", "no", "yes"]
    assert report.on is not None
    assert report.standby is not None
    assert diff(report.on, report.standby) == [
        ("FUNC_VIEW_INFO", "b_connect", None, False)
    ]
    power = [m async for m in _drain(soundbar) if m.get("cmd") == "set"]
    assert [m["data"] for m in power] == [{"b_powerkey": False}, {"b_powerkey": True}]
    text = render(report)
    assert f"- Standby with the remote: {TRANSITION_PUSHED}" in text
    assert "# standby with the remote" in text


async def test_gather_steps_can_be_skipped(soundbar: FakeSoundbar) -> None:
    """A device without a remote at hand can skip the remote steps."""
    answers = iter(["s", "s", "", "y"])

    async def ask(prompt: str) -> str:
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0)

    assert report.transitions == [
        ("Standby with the remote", TRANSITION_SKIPPED),
        ("On with the remote", TRANSITION_SKIPPED),
        ("Standby the usual way", TRANSITION_NOT_REPORTED),
    ]
    assert report.standby_remote is None
    assert report.on is None
    assert report.standby is not None
    # Power commands need the device to be on first
    assert {m["cmd"] async for m in _drain(soundbar)} == {"get"}


async def _drain(soundbar: FakeSoundbar):  # type: ignore[no-untyped-def]
    while not soundbar.received.empty():
        yield soundbar.received.get_nowait()


@pytest.mark.parametrize(
    ("argv", "target", "expected"),
    [
        pytest.param(
            ["report", "10.0.0.2"],
            "aiotemescal.report.main",
            ["10.0.0.2"],
            id="report",
        ),
        pytest.param(["10.0.0.2"], "aiotemescal.__main__._main", None, id="watch"),
    ],
)
def test_cli_dispatch(argv: list[str], target: str, expected: list[str] | None) -> None:
    """`report` runs the report, and a host alone still runs the watcher."""
    with (
        patch(target) as mock,
        patch(
            "aiotemescal.__main__.asyncio.run", side_effect=lambda coro: coro.close()
        ),
    ):
        main(argv)

    if expected is not None:
        mock.assert_called_once_with(expected)


@pytest.mark.parametrize("option", ["--guided", "--try-power", "--name-modes"])
def test_no_partial_report(option: str) -> None:
    """The report always does everything, so the old options are refused."""
    with pytest.raises(SystemExit):
        main(["report", "10.0.0.2", option])


async def test_unknown_sound_modes_are_named(soundbar: FakeSoundbar) -> None:
    """Each sound mode without a name is selected and named, then the mode is restored."""
    soundbar.answers["EQ_VIEW_INFO"] = {"ai_eq_list": [0, 24, 26], "i_curr_eq": 0}
    # Standby, still in standby, on, the two names, both power commands worked,
    # standby the usual way, still in standby
    answers = iter(["", "y", "", "Pure Voice", "", "y", "y", "", "y"])

    async def ask(prompt: str) -> str:
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0, mode_wait=0)

    assert report.mode_names == {24: "Pure Voice", 26: "nothing shown"}
    sent = [
        m["data"]
        async for m in _drain(soundbar)
        if m.get("cmd") == "set" and "i_curr_eq" in m.get("data", {})
    ]
    assert sent == [{"i_curr_eq": 24}, {"i_curr_eq": 26}, {"i_curr_eq": 0}]
    assert "| 24 | Pure Voice |" in render(report)


async def test_no_unknown_sound_modes_nothing_is_selected(
    soundbar: FakeSoundbar,
) -> None:
    """A device whose sound modes all have a name is left as it is."""
    soundbar.answers["EQ_VIEW_INFO"] = {"ai_eq_list": [0, 7], "i_curr_eq": 0}
    ask = AsyncMock(return_value="")

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0, mode_wait=0)

    assert report.mode_names == {}
    assert not [m async for m in _drain(soundbar) if "i_curr_eq" in m.get("data", {})]
    assert "Unknown sound modes" not in render(report)


async def test_gather_device_woken_by_requests(soundbar: FakeSoundbar) -> None:
    """A device woken by the state requests is put in standby again, not asked again."""
    # Standby, woken, standby again, on, both power commands worked, standby the
    # usual way, still in standby
    answers = iter(["", "n", "", "", "y", "y", "", "y"])
    received_before_turning_on: list[dict[str, object]] = []

    async def ask(prompt: str) -> str:
        if "standby again" in prompt:
            # Forget the requests made so far, to see what follows
            async for _ in _drain(soundbar):
                pass
        elif "on with its remote" in prompt:
            received_before_turning_on.extend([m async for m in _drain(soundbar)])
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0)

    assert received_before_turning_on == []
    question = (
        "Is it still in standby after being asked for its state"
        " (standby with the remote)?"
    )
    assert report.power_answers[question] == "no"
    assert report.on is not None


async def test_gather_power_command_ignored(soundbar: FakeSoundbar) -> None:
    """A power command that did nothing leads to the remote, not to a meaningless question."""
    answers = iter(["", "y", "", "n", "", "n", "", "", "y"])
    prompts: list[str] = []

    async def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0)

    after_off = prompts.index("Did `set_power(False)` put it in standby? [y/n]")
    assert prompts[after_off + 1].startswith("Put it in standby with its remote")
    assert prompts[after_off + 2] == "Did `set_power(True)` turn it on? [y/n]"
    assert prompts[after_off + 3].startswith("Turn it on with its remote")
    assert report.power_answers["Did `set_power(False)` put it in standby?"] == "no"
