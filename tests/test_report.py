"""Tests for the device report."""

import asyncio
from unittest.mock import patch

import pytest

from aiotemescal import TemescalClient
from aiotemescal.__main__ import main
from aiotemescal.report import (
    REDACTED,
    REPORT_MESSAGES,
    PowerTest,
    Report,
    Snapshot,
    analyse,
    collect,
    diff,
    gather,
    power_detection,
    redact,
    render,
    unanswered,
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


def test_diff_ignores_noise() -> None:
    """s_timezone holds fragments of other messages, so its changes mean nothing."""
    on = {**ON, "C4A_SETTING_INFO": {"s_timezone": 'd{"msg": "UPDATE_VIEW_INFO"}'}}
    standby = {**ON, "C4A_SETTING_INFO": {"s_timezone": "d"}}

    assert diff(on, standby) == []


def test_diff_ignores_unanswered_messages() -> None:
    """A message unanswered in one state is not shown as changed fields."""
    on = {**ON, "FUNC_VIEW_INFO": None, "SPK_LIST_VIEW_INFO": None}

    assert diff(on, STANDBY) == []
    assert unanswered(on, STANDBY) == [
        "`FUNC_VIEW_INFO` (on)",
        "`SPK_LIST_VIEW_INFO` (on)",
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


PUSHED_STANDBY = [("FUNC_VIEW_INFO", {"b_connect": False, "i_curr_func": 4})]
PUSHED_ON = [("FUNC_VIEW_INFO", {"b_connect": True, "i_curr_func": 20})]


@pytest.mark.parametrize(
    ("test", "conclusion"),
    [
        pytest.param(
            PowerTest(
                on=ON,
                standby=STANDBY,
                woken_by_reading=True,
                pushed={"standby": PUSHED_STANDBY, "on": PUSHED_ON},
            ),
            "can be followed from what the device sends by itself"
            " (`b_connect`, `i_curr_func`)",
            id="pushed",
        ),
        pytest.param(
            PowerTest(
                on=ON,
                standby=STANDBY,
                woken_by_reading=False,
                pushed={"standby": PUSHED_STANDBY},
            ),
            "can be read by asking for",
            id="asked",
        ),
        pytest.param(
            PowerTest(on=ON, standby=STANDBY, woken_by_reading=True),
            "cannot be followed: neither change is sent by itself, and reading the"
            " state in standby turns it on",
            id="woken",
        ),
        pytest.param(
            PowerTest(
                on=ON,
                standby=STANDBY,
                woken_by_reading=True,
                pushed={"standby": [], "on": PUSHED_ON},
            ),
            "cannot be followed: only turning on is sent by itself",
            id="only on pushed",
        ),
        pytest.param(
            PowerTest(on=ON, standby=ON, woken_by_reading=False),
            "no field differs between on and standby when asked",
            id="nothing changes",
        ),
    ],
)
def test_power_detection(test: PowerTest, conclusion: str) -> None:
    """The report concludes whether, and how, the power state can be followed."""
    assert conclusion in power_detection(test)[-1]


def test_power_detection_connection_lost() -> None:
    """A device that leaves the network in standby is reported as such."""
    text = render(Report(snapshot=ON, power={"TV": PowerTest(on=ON)}))

    assert "The connection was lost during a power change" in text


def test_render_redacted() -> None:
    """The report has the findings and the on/standby table, without identifying data."""
    report = Report(
        snapshot=ON,
        power={
            "remote": PowerTest(
                on=ON,
                standby=STANDBY,
                woken_by_reading=False,
                pushed={"standby": [("FUNC_VIEW_INFO", {"s_spk_bt_name": "Salle TV"})]},
            )
        },
        timeline=[(1.5, "`FUNC_VIEW_INFO`", {"s_spk_bt_name": "Salle TV"})],
    )

    text = render(report)

    assert "- Model: SP8YA" in text
    assert "### Power detection with the remote" in text
    assert "| `FUNC_VIEW_INFO` | `b_connect` | `True` | `False` |" in text
    assert "Reading the state in standby turned it on: **no**" in text
    assert '  - `FUNC_VIEW_INFO` `{"s_spk_bt_name": "<redacted>"}`' in text
    assert "# standby with the remote" in text
    for value in IDENTIFYING:
        assert value not in text


def test_render_not_redacted() -> None:
    """--no-redact keeps the names and addresses."""
    assert "192.168.1.127" in render(Report(snapshot=ON), redacted=False)


async def test_gather(soundbar: FakeSoundbar) -> None:
    """Each power change, with the remote then the TV, records what is sent by itself."""
    soundbar.answers["FUNC_VIEW_INFO"] = dict(ON["FUNC_VIEW_INFO"] or {})
    # Follows the TV, then for each way: ready, standby, still in standby, on
    answers = iter(["y", "", "", "y", "", "", "", "y", ""])

    async def ask(prompt: str) -> str:
        # Only the changes that follow the TV are reported, as on the SP8YA
        if prompt.startswith("Turn the TV off"):
            new = {"b_connect": False, "i_curr_func": 4}
        elif prompt.startswith("Turn the TV on, "):
            new = {"b_connect": True, "i_curr_func": 20}
        else:
            return next(answers)
        soundbar.answers["FUNC_VIEW_INFO"].update(new)
        await soundbar.push({"cmd": "notibyset", "msg": "FUNC_VIEW_INFO", "data": new})
        # The user presses Enter once the device has changed
        await asyncio.sleep(0.1)
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0, settle_wait=0)

    assert list(report.power) == ["remote", "TV"]
    assert report.power["remote"].pushed == {"standby": [], "on": []}
    assert report.power["TV"].pushed == {
        "standby": [("FUNC_VIEW_INFO", {"b_connect": False, "i_curr_func": 4})],
        "on": [("FUNC_VIEW_INFO", {"b_connect": True, "i_curr_func": 20})],
    }
    assert report.power["TV"].woken_by_reading is False
    assert "neither change" in power_detection(report.power["remote"])[-1]
    assert "sends by itself" in power_detection(report.power["TV"])[-1]
    # Nothing but requests is sent to a device whose sound modes all have a name
    assert {m["cmd"] async for m in _drain(soundbar)} == {"get"}


async def test_gather_without_tv(soundbar: FakeSoundbar) -> None:
    """A device that does not follow a TV is only tested with its remote."""
    answers = iter(["n", "", "", "y", ""])

    async def ask(prompt: str) -> str:
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0, settle_wait=0)

    assert list(report.power) == ["remote"]


async def test_gather_device_woken_by_reading(soundbar: FakeSoundbar) -> None:
    """A device woken by reading its state is put in standby again, not asked again."""
    answers = iter(["n", "", "", "n", "", ""])
    received_before_turning_on: list[dict[str, object]] = []

    async def ask(prompt: str) -> str:
        if "standby again" in prompt:
            # Forget the requests made so far, to see what follows
            async for _ in _drain(soundbar):
                pass
        elif prompt.startswith("Turn the device on"):
            received_before_turning_on.extend([m async for m in _drain(soundbar)])
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0, settle_wait=0)

    assert received_before_turning_on == []
    assert report.power["remote"].woken_by_reading is True
    assert report.power["remote"].on is not None


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
    """Each sound mode without a name is selected and named, then restored."""
    soundbar.answers["EQ_VIEW_INFO"] = {"ai_eq_list": [0, 24, 26], "i_curr_eq": 0}
    # No TV, ready, standby, still in standby, on, then the two names
    answers = iter(["n", "", "", "y", "", "Pure Voice", ""])

    async def ask(prompt: str) -> str:
        return next(answers)

    async with TemescalClient(
        "127.0.0.1", soundbar.port, response_timeout=0.2
    ) as client:
        report = await gather(client, ask=ask, power_wait=0, settle_wait=0, mode_wait=0)

    assert report.mode_names == {24: "Pure Voice", 26: "nothing shown"}
    sent = [m["data"] async for m in _drain(soundbar) if m.get("cmd") == "set"]
    assert sent == [{"i_curr_eq": 24}, {"i_curr_eq": 26}, {"i_curr_eq": 0}]
    assert "| 24 | Pure Voice |" in render(report)
