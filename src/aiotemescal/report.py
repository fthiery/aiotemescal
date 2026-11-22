"""Collect what a device reports, to help support new models.

Run ``aiotemescal report HOST`` at the device and paste the output into an
issue. It asks you to put the device in standby and to turn it on, with its
remote and then with the TV, to find out whether its power state can be
followed, and selects each sound mode without a name before restoring the
current one.
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib import metadata
import json
import platform
import re
import sys
import time
from typing import Any

from .client import STATE_MESSAGES, TemescalClient
from .const import (
    DEFAULT_PORT,
    MSG_C4A_SETTING_INFO,
    MSG_EQ_VIEW_INFO,
    MSG_FUNC_VIEW_INFO,
    MSG_MAC_INFO_DEV,
    MSG_PRODUCT_INFO,
    MSG_SPK_LIST_VIEW_INFO,
    MSG_UPDATE_VIEW_INFO,
    equalisers,
    functions,
)
from .exceptions import TemescalConnectionError, TemescalTimeoutError

REPORT_MESSAGES = (
    *STATE_MESSAGES,
    MSG_PRODUCT_INFO,
    MSG_UPDATE_VIEW_INFO,
    MSG_MAC_INFO_DEV,
    MSG_C4A_SETTING_INFO,
)

# Devices ignore some messages, so waiting the client default for each is slow
RESPONSE_TIMEOUT = 2.0
# Time given to the device to wake up after its state was read in standby
POWER_WAIT = 10.0
# Time given to the device to settle after the user changed its power state,
# so that the messages it sends by itself arrive before its state is read
SETTLE_WAIT = 10.0
# How long to try connecting again when the connection was lost, for example
# while the device restarts or loses its Wi-Fi for a moment
RECONNECT_FOR = 60.0
# Time given to the device to show a sound mode before asking for its name
MODE_WAIT = 2.0

# Ways of changing the power state: name, how to prepare, how to put the device
# in standby, how to put it back in standby after reading its state woke it, and
# how to turn it on
METHODS = (
    (
        "remote",
        "Make sure the device is on",
        "Put the device in standby with its remote or its own button, and wait"
        " until it is in standby (display off)",
        "Put it in standby again with its remote or its own button",
        "Turn the device on with its remote or its own button",
    ),
    (
        "TV",
        "Make sure the TV is on and the device is on with it",
        "Turn the TV off, and wait until the device follows it into standby"
        " (display off)",
        "Turn the TV on then off again, so that the device follows it into standby",
        "Turn the TV on, and wait until the device follows it",
    ),
)
QUESTION_FOLLOWS_TV = (
    "Does the device turn on and off with the TV (HDMI ARC or eARC, optical)?"
)

# Fields that change from one read to the next whatever the power state: the
# SP8YA puts fragments of the previous message in s_timezone
NOISE = {(MSG_C4A_SETTING_INFO, "s_timezone")}

REDACTED = "<redacted>"
_REDACTED_KEYS = re.compile(r"(ssid|mac|uuid|ip(v[46])?_addr|user_name|bt_name)")
_REDACTED_VALUES = re.compile(
    r"([0-9a-f]{2}[:-]){5}[0-9a-f]{2}"  # MAC address
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUID
    r"|\b\d{1,3}(\.\d{1,3}){3}\b"  # IPv4 address
    r"|\b[0-9a-f]{1,4}(:[0-9a-f]{0,4}){3,7}\b",  # IPv6 address
    re.IGNORECASE,
)

type Snapshot = dict[str, dict[str, Any] | None]
type Ask = Callable[[str], Awaitable[str]]


@dataclass
class PowerTest:
    """A power change to standby then back on, made one way."""

    standby: Snapshot | None = None
    on: Snapshot | None = None
    # Whether reading the state in standby turned the device on
    woken_by_reading: bool | None = None
    # Messages the device sent by itself while going to "standby", then "on"
    pushed: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)
    # Connections lost while the device was in standby, then while it was on
    lost: dict[str, int] = field(default_factory=dict)


@dataclass
class Report:
    """Everything collected from a device."""

    snapshot: Snapshot
    # One test per way of changing the power state, by METHODS name
    power: dict[str, PowerTest] = field(default_factory=dict)
    # Name shown on the display of the device for each unknown sound mode
    mode_names: dict[int, str] = field(default_factory=dict)
    # Seconds since the start, what happened, and the data of a message
    timeline: list[tuple[float, str, Any]] = field(default_factory=list)


async def collect(client: TemescalClient) -> Snapshot:
    """Ask for every known message; None means the device did not answer."""
    snapshot: Snapshot = {}
    for msg in REPORT_MESSAGES:
        try:
            snapshot[msg] = (await client.request(msg)).get("data") or {}
        except TemescalTimeoutError:
            snapshot[msg] = None
    return snapshot


def _data(snapshot: Snapshot, msg: str) -> dict[str, Any]:
    return snapshot.get(msg) or {}


def _names(table: list[str], indices: list[int]) -> str:
    return ", ".join(
        f"{index} ({table[index]})" if index < len(table) else f"{index} (unknown)"
        for index in indices
    )


def analyse(snapshot: Snapshot) -> list[str]:
    """Return what the snapshot tells about the device, in plain language."""
    findings: list[str] = []
    product = _data(snapshot, MSG_PRODUCT_INFO)
    findings.append(f"Model: {product.get('s_model_name', 'not reported')}")

    versions = _data(snapshot, MSG_UPDATE_VIEW_INFO).get("o_system_ver") or {}
    if versions:
        findings.append(
            "Firmware (main / micom / Chromecast): "
            + " / ".join(
                str(versions.get(key, "?")) for key in ("s_main", "s_micom", "s_c4a")
            )
        )
    else:
        findings.append("Firmware: not reported")

    reported = {key for data in snapshot.values() if data for key in data}
    if "b_powerstatus" in reported:
        findings.append("Power state: reported (`b_powerstatus`)")
    else:
        findings.append(
            "Power state: not reported (no `b_powerstatus`), see Power detection"
        )
    findings.append(
        "Unique id: "
        + (
            "reported (`s_uuid`)"
            if "s_uuid" in reported
            else "not reported (no `s_uuid`)"
        )
    )

    for msg, key, table, label in (
        (MSG_FUNC_VIEW_INFO, "ai_func_list", functions, "Inputs"),
        (MSG_EQ_VIEW_INFO, "ai_eq_list", equalisers, "Sound modes"),
    ):
        if indices := _data(snapshot, msg).get(key):
            findings.append(f"{label} offered: {_names(table, indices)}")
            if unknown := [index for index in indices if index >= len(table)]:
                findings.append(
                    f"{label} without a name in aiotemescal: "
                    + ", ".join(map(str, unknown))
                )

    current = _data(snapshot, MSG_SPK_LIST_VIEW_INFO).get("i_curr_func")
    if current is not None:
        findings.append(f"Current input: {_names(functions, [current])}")

    if unanswered := [msg for msg, data in snapshot.items() if data is None]:
        findings.append("No answer to: " + ", ".join(f"`{msg}`" for msg in unanswered))
    return findings


def diff(before: Snapshot, after: Snapshot) -> list[tuple[str, str, Any, Any]]:
    """Return the fields that differ between two snapshots.

    Only messages answered in both are compared: a message left unanswered says
    nothing about the fields it would have carried. Known noise is left out.
    """
    changes = []
    for msg in before.keys() & after.keys():
        old, new = before[msg], after[msg]
        if old is None or new is None:
            continue
        for key in old.keys() | new.keys():
            if (msg, key) not in NOISE and old.get(key) != new.get(key):
                changes.append((msg, key, old.get(key), new.get(key)))
    return sorted(changes)


def unanswered(on: Snapshot, standby: Snapshot) -> list[str]:
    """Return the messages answered in only one of the two states, and where not."""
    return sorted(
        f"`{msg}` ({'on' if on.get(msg) is None else 'standby'})"
        for msg in on.keys() | standby.keys()
        if (on.get(msg) is None) != (standby.get(msg) is None)
    )


def _pushed_values(test: PowerTest, step: str) -> dict[tuple[str, str], Any]:
    """Return the last value of each field the device sent by itself in a step."""
    values: dict[tuple[str, str], Any] = {}
    for msg, data in test.pushed.get(step, []):
        if isinstance(data, dict):
            values.update(((msg, key), value) for key, value in data.items())
    return values


def _sent(test: PowerTest, step: str) -> list[str]:
    """Describe the messages the device sent by itself in a step, in order."""
    sent: list[str] = []
    for msg, data in test.pushed.get(step, []):
        line = f"`{msg}` `{json.dumps(data, sort_keys=True)}`"
        if not sent or sent[-1] != line:
            sent.append(line)
    return sent


def power_detection(test: PowerTest) -> list[str]:
    """Say whether, and how, a power change made one way can be followed."""
    if test.on is None or test.standby is None:
        return [
            "The device could not be reached after a power change, so no state"
            " could be compared."
        ]
    lines = []
    for step, name in (("standby", "Going to standby"), ("on", "Turning on")):
        sent = _sent(test, step)
        lines.append(
            f"{name}: " + ("sent nothing by itself" if not sent else "sent by itself:")
        )
        lines += [f"  - {line}" for line in sent]
    if test.lost:
        lines.append(
            "Connection lost: "
            + ", ".join(
                f"{count} time{'s' if count > 1 else ''} in {step}"
                for step, count in test.lost.items()
            )
        )
    if test.woken_by_reading is not None:
        lines.append(
            "Reading the state in standby turned it on: "
            + ("**yes**" if test.woken_by_reading else "**no**")
        )

    standby_values = _pushed_values(test, "standby")
    on_values = _pushed_values(test, "on")
    pushed_fields = sorted(
        f"`{key}`"
        for (msg, key), value in on_values.items()
        if (msg, key) in standby_values
        and (msg, key) not in NOISE
        and standby_values[(msg, key)] != value
    )
    # A state read in standby means nothing once reading it turned the device on
    changes = [] if test.woken_by_reading else diff(test.on, test.standby)
    fields = ", ".join(sorted({f"`{key}`" for _, key, _, _ in changes}))
    if pushed_fields:
        conclusion = (
            "the power state can be followed from what the device sends by itself"
            f" ({', '.join(pushed_fields)})"
        )
    elif changes:
        conclusion = (
            f"the power state can be read by asking for {fields}, which leaves"
            " the device in standby"
        )
    else:
        if standby_values and on_values:
            sent = "both changes are sent by itself, but with the same values"
        elif on_values:
            sent = "only turning on is sent by itself"
        elif standby_values:
            sent = "only going to standby is sent by itself"
        else:
            sent = "neither change is sent by itself"
        asked = (
            "reading the state in standby turns it on"
            if test.woken_by_reading
            else "no field differs between on and standby when asked"
        )
        conclusion = f"the power state cannot be followed: {sent}, and {asked}"
    lines.append(f"**Conclusion**: {conclusion}")
    return lines


def redact(value: Any) -> Any:
    """Hide the addresses, identifiers and names a report would otherwise show."""
    if isinstance(value, dict):
        return {
            key: REDACTED
            if _REDACTED_KEYS.search(key) and value[key] not in ("", None)
            else redact(value[key])
            for key in value
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _REDACTED_VALUES.sub(REDACTED, value)
    return value


def _redact_report(report: Report) -> Report:
    return Report(
        snapshot=redact(report.snapshot),
        power={
            method: PowerTest(
                standby=redact(test.standby),
                on=redact(test.on),
                woken_by_reading=test.woken_by_reading,
                lost=test.lost,
                pushed={
                    step: [(msg, redact(data)) for msg, data in messages]
                    for step, messages in test.pushed.items()
                },
            )
            for method, test in report.power.items()
        },
        mode_names=report.mode_names,
        timeline=[(when, event, redact(data)) for when, event, data in report.timeline],
    )


def _version() -> str:
    try:
        return metadata.version("aiotemescal")
    except metadata.PackageNotFoundError:
        return "unknown"


def render(report: Report, *, redacted: bool = True) -> str:
    """Return the report as Markdown, ready to paste into an issue."""
    if redacted:
        report = _redact_report(report)
    lines = [
        "## aiotemescal device report",
        "",
        (
            f"aiotemescal {_version()}, Python {platform.python_version()},"
            f" {platform.system()} {platform.machine()}"
        ),
        "",
        "### Findings",
        "",
        *(f"- {finding}" for finding in analyse(report.snapshot)),
    ]

    for method, test in report.power.items():
        lines += ["", f"### Power detection with the {method}", ""]
        lines += [
            line if line.startswith("  ") else f"- {line}"
            for line in power_detection(test)
        ]
        if test.on is None or test.standby is None:
            continue
        if test.woken_by_reading:
            lines += [
                "",
                "The state read in standby is not compared, since reading it turned"
                " the device on.",
            ]
        elif changes := diff(test.on, test.standby):
            lines += [
                "",
                "| Message | Field | On | Standby |",
                "| --- | --- | --- | --- |",
            ]
            lines += [
                f"| `{msg}` | `{key}` | `{old!r}` | `{new!r}` |"
                for msg, key, old, new in changes
            ]
        if missing := unanswered(test.on, test.standby):
            lines += ["", "Not answered in one of the states: " + ", ".join(missing)]

    if report.mode_names:
        lines += [
            "",
            "### Unknown sound modes",
            "",
            "| `i_curr_eq` | Name shown |",
            "| --- | --- |",
        ]
        lines += [f"| {index} | {name} |" for index, name in report.mode_names.items()]

    if report.timeline:
        lines += ["", "### Timeline", "", "| Time | Event |", "| --- | --- |"]
        lines += [
            f"| {when:7.1f} s | {event}"
            + ("" if data is None else f" `{json.dumps(data, sort_keys=True)}`")
            + " |"
            for when, event, data in report.timeline
        ]

    states = {"current": report.snapshot}
    for method, test in report.power.items():
        states[f"standby with the {method}"] = test.standby
        states[f"on with the {method}"] = test.on
    lines += ["", "<details><summary>Full state</summary>", "", "```text"]
    for name, snapshot in states.items():
        if snapshot is not None:
            lines.append(f"# {name}")
            lines += [
                f"{msg}: {json.dumps(data, sort_keys=True)}"
                for msg, data in sorted(snapshot.items())
            ]
    lines += ["```", "", "</details>", ""]
    return "\n".join(lines)


async def _ask(prompt: str) -> str:
    """Ask on the terminal without blocking the messages that keep arriving."""
    sys.stderr.write(f"{prompt} ")
    sys.stderr.flush()
    line: str = await asyncio.to_thread(sys.stdin.readline)
    return line.strip()


async def _yes_no(ask: Ask, question: str) -> str:
    answer = await ask(f"{question} [y/n]")
    return "yes" if answer.lower().startswith("y") else "no"


async def _reconnect(client: TemescalClient, reconnect_for: float) -> bool:
    """Open the connection again if it was lost, without sending anything.

    Opening a connection does not wake a device in standby, unlike a request.
    """
    deadline = time.monotonic() + reconnect_for
    while not client.connected:
        try:
            await client.connect()
        except TemescalConnectionError:
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(1)
    return True


async def _collect_or_none(
    client: TemescalClient, reconnect_for: float = RECONNECT_FOR
) -> Snapshot | None:
    """Read the state, connecting again first if needed; None if unreachable."""
    for _ in range(2):
        if not await _reconnect(client, reconnect_for):
            return None
        try:
            return await collect(client)
        except TemescalConnectionError:
            # Lost while reading: read everything again on a new connection
            continue
    return None


async def gather(
    client: TemescalClient,
    *,
    ask: Ask = _ask,
    power_wait: float = POWER_WAIT,
    settle_wait: float = SETTLE_WAIT,
    reconnect_for: float = RECONNECT_FOR,
    mode_wait: float = MODE_WAIT,
) -> Report:
    """Collect a full report from a connected client, asking the user along the way."""
    start = time.monotonic()
    timeline: list[tuple[float, str, Any]] = []

    def note(event: str, data: Any = None) -> None:
        timeline.append((time.monotonic() - start, event, data))

    # Messages the device sent by itself, not as an answer to the report
    pushed: list[tuple[str, Any]] = []

    def on_message(message: dict[str, Any]) -> None:
        # Answers to the requests of the report are in the snapshots already
        if message.get("cmd") != "notibyget":
            pushed.append((message.get("msg", ""), message.get("data")))
            note(f"`{message.get('msg')}`", message.get("data"))

    # The power test under way, and the state the user last put the device in
    current: list[tuple[PowerTest, str]] = []

    def on_connection(connected: bool) -> None:
        note("connected" if connected else "connection lost")
        if not connected and current:
            test, state = current[-1]
            test.lost[state] = test.lost.get(state, 0) + 1

    unsubscribe = (
        client.subscribe(on_message),
        client.subscribe_connection(on_connection),
    )

    async def name_unknown_modes(snapshot: Snapshot, *, is_on: bool) -> None:
        """Select each sound mode without a name, ask for its name, then restore."""
        eq = _data(snapshot, MSG_EQ_VIEW_INFO)
        unknown = [i for i in eq.get("ai_eq_list") or [] if i >= len(equalisers)]
        original = eq.get("i_curr_eq")
        if unknown and not is_on:
            await ask("Make sure the device is on, then press Enter.")
        try:
            for index in unknown:
                note(f"sent set_eq({index})")
                await client.set_eq(index)
                await asyncio.sleep(mode_wait)
                name = await ask(
                    f"Sound mode {index} is selected. What name does the display of"
                    " the soundbar show? (just Enter if none)"
                )
                report.mode_names[index] = name or "nothing shown"
        finally:
            if unknown and original is not None:
                note(f"sent set_eq({original})")
                await client.set_eq(original)

    try:
        report = Report(snapshot=await collect(client), timeline=timeline)

        async def change(test: PowerTest, step: str, prompt: str) -> Snapshot | None:
            """Let the user change the power state, then read the new state."""
            mark = len(pushed)
            await ask(prompt + ", then press Enter.")
            note(f"user: {step}")
            current.append((test, step))
            await asyncio.sleep(settle_wait)
            test.pushed[step] = pushed[mark:]
            snapshot = await _collect_or_none(client, reconnect_for)
            if snapshot is None:
                note("could not reach the device")
            return snapshot

        follows_tv = await _yes_no(ask, QUESTION_FOLLOWS_TV) == "yes"
        for method, prepare, to_standby, to_standby_again, to_on in METHODS:
            if method == "TV" and not follows_tv:
                continue
            # Recorded from here, so that the preparation is not taken for a change
            await ask(prepare + ", then press Enter.")
            note(f"user: ready for the test with the {method}")
            # Let the messages that follow the preparation arrive before recording
            await asyncio.sleep(settle_wait)
            test = report.power[method] = PowerTest()
            test.standby = await change(test, "standby", to_standby)
            if test.standby is not None:
                # Some models (SP8YA) turn on when they receive any request in standby
                note("asked for the state in standby")
                await asyncio.sleep(power_wait)
                test.woken_by_reading = (
                    await _yes_no(
                        ask, "Is it still in standby now that its state was read?"
                    )
                ) == "no"
                if test.woken_by_reading:
                    await ask(
                        to_standby_again + ", wait until it is done, then press Enter."
                    )
                    note("user: standby again")
                    current.append((test, "standby"))
            test.on = await change(test, "on", to_on)

        last_on = next(
            (test.on for test in reversed(report.power.values()) if test.on), None
        )
        if await _reconnect(client, reconnect_for):
            await name_unknown_modes(
                last_on or report.snapshot, is_on=last_on is not None
            )
        return report
    finally:
        for callback in unsubscribe:
            callback()


async def _run(args: argparse.Namespace) -> str:
    client = TemescalClient(args.host, args.port, response_timeout=RESPONSE_TIMEOUT)
    async with client:
        report = await gather(client)
    return render(report, redacted=not args.no_redact)


def main(argv: list[str] | None = None) -> None:
    """Run ``aiotemescal report``."""
    parser = argparse.ArgumentParser(prog="aiotemescal report", description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--no-redact", action="store_true", help="keep addresses, identifiers and names"
    )
    parser.add_argument("-o", "--output", help="write the report to this file")
    args = parser.parse_args(argv)
    sys.stderr.write(
        "Run the report at the device, with its remote: it asks you to put the"
        " device in standby and to turn it on, with its remote and then with the"
        " TV, and selects each sound mode without a name before restoring the"
        " current one.\n"
    )
    sys.stderr.write(
        "Keep the LG app closed and the Home Assistant integration disabled during"
        " the report: they query the device, which interferes with what the report"
        " observes.\n"
    )

    try:
        text = asyncio.run(_run(args))
    except TemescalConnectionError as err:
        parser.exit(1, f"Cannot reach the device: {err}\n")
    except KeyboardInterrupt:
        parser.exit(130, "\nInterrupted\n")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(text)
        sys.stderr.write(f"Report written to {args.output}\n")
    else:
        sys.stdout.write(text)
