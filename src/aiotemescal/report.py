"""Collect what a device reports, to help support new models.

Run ``aiotemescal report HOST`` and paste the output into an issue. Nothing
that changes the device is sent unless ``--try-power`` is given.
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
# Time given to the device to settle after a power command
POWER_WAIT = 10.0

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
class Report:
    """Everything collected from a device."""

    snapshot: Snapshot
    on: Snapshot | None = None
    standby: Snapshot | None = None
    power_answers: dict[str, str] = field(default_factory=dict)
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
            "Power state: not reported (no `b_powerstatus`), run with --guided to"
            " find out which fields change between on and standby"
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
    """Return the fields that differ between two snapshots."""
    changes = []
    for msg in before.keys() | after.keys():
        old, new = before.get(msg) or {}, after.get(msg) or {}
        for key in old.keys() | new.keys():
            if old.get(key) != new.get(key):
                changes.append((msg, key, old.get(key), new.get(key)))
    return sorted(changes)


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
        on=redact(report.on),
        standby=redact(report.standby),
        power_answers=report.power_answers,
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

    if report.on is not None:
        lines += ["", "### On and standby", ""]
        if report.standby is None:
            lines.append(
                "The connection was lost in standby, so no state could be read."
            )
        elif changes := diff(report.on, report.standby):
            lines += ["| Message | Field | On | Standby |", "| --- | --- | --- | --- |"]
            lines += [
                f"| `{msg}` | `{key}` | `{old!r}` | `{new!r}` |"
                for msg, key, old, new in changes
            ]
        else:
            lines.append("No field changed between on and standby.")

    if report.power_answers:
        lines += ["", "### Power", ""]
        lines += [
            f"- {question} **{answer}**"
            for question, answer in report.power_answers.items()
        ]

    if report.timeline:
        lines += ["", "### Timeline", "", "| Time | Event |", "| --- | --- |"]
        lines += [
            f"| {when:7.1f} s | {event}"
            + ("" if data is None else f" `{json.dumps(data, sort_keys=True)}`")
            + " |"
            for when, event, data in report.timeline
        ]

    states = {"current": report.snapshot, "on": report.on, "standby": report.standby}
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


async def _collect_or_none(client: TemescalClient) -> Snapshot | None:
    try:
        return await collect(client)
    except TemescalConnectionError:
        return None


async def gather(
    client: TemescalClient,
    *,
    guided: bool = False,
    try_power: bool = False,
    ask: Ask = _ask,
    power_wait: float = POWER_WAIT,
) -> Report:
    """Collect a report from a connected client, asking the user when guided."""
    start = time.monotonic()
    timeline: list[tuple[float, str, Any]] = []

    def note(event: str, data: Any = None) -> None:
        timeline.append((time.monotonic() - start, event, data))

    def on_message(message: dict[str, Any]) -> None:
        # Answers to the requests of the report are in the snapshots already
        if message.get("cmd") != "notibyget":
            note(f"`{message.get('msg')}`", message.get("data"))

    def on_connection(connected: bool) -> None:
        note("connected" if connected else "connection lost")

    unsubscribe = (
        client.subscribe(on_message),
        client.subscribe_connection(on_connection),
    )
    try:
        report = Report(snapshot=await collect(client), timeline=timeline)
        if not guided:
            return report

        await ask(
            "Turn the device on (for example by turning the TV on), then press Enter."
        )
        note("user: device on")
        report.on = await _collect_or_none(client)

        if try_power and report.on is not None:
            note("sent set_power(False)")
            await client.set_power(False)
            await asyncio.sleep(power_wait)
            question = "Did `set_power(False)` put it in standby?"
            report.power_answers[question] = await _yes_no(ask, question)
            note("sent set_power(True)")
            await client.set_power(True)
            await asyncio.sleep(power_wait)
            question = "Did `set_power(True)` turn it back on?"
            report.power_answers[question] = await _yes_no(ask, question)
            await ask("Make sure it is on again, then press Enter.")

        await ask(
            "Put the device in standby the way you usually do (TV off, remote),"
            " wait 30 seconds, then press Enter."
        )
        note("user: device in standby")
        report.standby = await _collect_or_none(client)
        if report.standby is not None:
            # Some models are said to wake up when asked for their state in standby
            note("asked for the state in standby")
            await asyncio.sleep(power_wait)
            question = "Is it still in standby after being asked for its state?"
            report.power_answers[question] = await _yes_no(ask, question)
        return report
    finally:
        for callback in unsubscribe:
            callback()


async def _run(args: argparse.Namespace) -> str:
    client = TemescalClient(args.host, args.port, response_timeout=RESPONSE_TIMEOUT)
    async with client:
        report = await gather(client, guided=args.guided, try_power=args.try_power)
    return render(report, redacted=not args.no_redact)


def main(argv: list[str] | None = None) -> None:
    """Run ``aiotemescal report``."""
    parser = argparse.ArgumentParser(prog="aiotemescal report", description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--guided",
        action="store_true",
        help="ask you to turn the device on and off, and compare its state",
    )
    parser.add_argument(
        "--try-power",
        action="store_true",
        help="with --guided, send the power commands and ask whether they worked",
    )
    parser.add_argument(
        "--no-redact", action="store_true", help="keep addresses, identifiers and names"
    )
    parser.add_argument("-o", "--output", help="write the report to this file")
    args = parser.parse_args(argv)
    if args.try_power and not args.guided:
        parser.error("--try-power needs --guided")
    if args.try_power:
        sys.stderr.write(
            "--try-power sends the power commands, which turn the device off and on.\n"
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
