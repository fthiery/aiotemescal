# aiotemescal

Asyncio client for LG soundbars and Wi-Fi speakers, speaking the "temescal"
protocol used by the LG Wi-Fi Speaker app (TCP port 9741).

It is a rewrite of [python-temescal](https://github.com/google/python-temescal),
which was not designed for devices that are only intermittently present on the
network, for example a soundbar powered through a smart plug. It is used by the
[LG Soundbars](https://www.home-assistant.io/integrations/lg_soundbar)
integration of Home Assistant.

Features:

- the connection is kept open in the background and re-established with an
  exponential backoff;
- a power cut is noticed within seconds through tuned TCP keepalive and
  `TCP_USER_TIMEOUT`, without any application traffic (on Linux, see
  [Power loss detection](#power-loss-detection));
- the backoff can be skipped when you know the device is back, and the
  address can be changed without restarting the client;
- after each connection, the whole state is requested and delivered to
  subscribers before the connection is reported, so a device that comes back
  is never shown with the state it had before;
- connection state changes are reported to subscribers;
- requests can be awaited for their answer.

## Usage

```python
import asyncio
from aiotemescal import TemescalClient


async def main() -> None:
    client = TemescalClient("192.168.1.15")
    client.subscribe(print)
    client.subscribe_connection(lambda up: print("connected" if up else "gone"))
    await client.start()
    ...
    await client.stop()


asyncio.run(main())
```

One-shot use, for example to identify a device:

```python
async with TemescalClient("192.168.1.15") as client:
    info = await client.request("SPK_LIST_VIEW_INFO")
    print(info["data"]["s_user_name"])
```

`request()` and `send()` raise `TemescalConnectionError` when the device is not
connected or does not acknowledge them, and `request()` raises `TemescalTimeoutError` when no answer arrives.

Every message received from the device is delivered to the `subscribe()`
callbacks, including answers to requests and unsolicited status updates.

## Reconnection

While the device is unreachable, the client retries with a backoff that grows
from 1 to 5 s. If you learn by other means that the device is back, call
`reconnect_now()` to retry right away; it does nothing while connected.
`set_host()` changes the address of the device and retries right away.

A device can also disconnect on its own; the [device pages](#tested-devices)
list the cases observed on each model.

## Power loss detection

A device that loses power stops acknowledging TCP packets. The client
configures the socket so that the kernel closes such a connection after about
7 s when idle (keepalive probes after 5 s of silence, every second, two
missed), or 3 s after a command that is not acknowledged.

Commands wait for the device to acknowledge them at the TCP level before
returning, which takes a few milliseconds on a local network. A command sent to
a device that just lost power therefore raises `TemescalConnectionError` once
the connection is closed, instead of returning as if it had been delivered.

**This relies on Linux socket options.** Each option is only set when Python
exposes it on the running system, and `TCP_USER_TIMEOUT` only exists on Linux.
Where an option is missing, the default of the operating system applies, which
is often two hours of silence before the first keepalive probe. Since the client
sends no application-level heartbeat, a device that loses power while the
connection is idle can then go unnoticed for that long. Home Assistant OS and
other Linux hosts are not affected.

## Debugging

```
python -m aiotemescal 192.168.1.15 -v
```

prints every message and connection change; use it while cutting power to the
device to see how quickly the loss and the return are detected.

## Tests

```
make test                                          # unit tests, against a fake soundbar
make test-live TEMESCAL_HOST=192.168.1.127         # read-only tests against a real device
make test-actions TEMESCAL_HOST=192.168.1.127      # changes and restores settings, input and power
make test-power-cycle TEMESCAL_HOST=192.168.1.127  # asks you to unplug and replug it, twice
```

`TEMESCAL_PORT` overrides the default port 9741.

## Tested devices

| Model | Firmware (main / micom / Chromecast) | Notes |
| --- | --- | --- |
| LG SP8YA | 2407090 / 2207202 / 1.56.310669 | [device page](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/lg-sp8ya.md) |

The versions are those reported in `UPDATE_VIEW_INFO`. Each device page
gathers what was learned on that model: how it identifies itself, when it
disconnects by itself, and what it supports, such as power control.

## Contributing

Only one model has been tested so far, and models differ: some report their
power state and others do not, some offer inputs or sound modes that have no
name in this library yet. A report from your device is the most useful
contribution, even if everything works.

### Report your device

With [uv](https://docs.astral.sh/uv/), from any machine on the same network as
the device:

```
uvx aiotemescal report 192.168.1.15                         # read-only
uvx aiotemescal report 192.168.1.15 --guided                # asks you to turn it on, then to standby
uvx aiotemescal report 192.168.1.15 --guided --try-power    # also tries the power commands
```

- Without options, the report only asks the device for its state: nothing is
  changed. It lists what the device reports, the inputs and sound modes it
  offers, and the messages it does not answer.
- `--guided` asks you to turn the device on, then to put it in standby the way
  you usually do (TV off, remote), and compares its full state in both cases.
  It also records every message the device sends by itself in the meantime.
  This shows whether, and how, its power state can be followed.
- `--try-power` also sends the power commands, which turn the device off and
  on, and asks you whether they worked. It is the only option that changes the
  device.

The report is printed as Markdown, ready to paste (`-o FILE` writes it to a
file). IP addresses, MAC addresses, UUIDs and the names you gave the device are
replaced with `<redacted>`; `--no-redact` keeps them. Read it before posting.

Then [open an issue](https://github.com/fthiery/aiotemescal//issues/new?template=device_report.md)
with the report, and anything you noticed that the report cannot see: how the
device is connected to the TV, whether it loses the connection by itself, what
the LG app shows for an unknown sound mode.

Example, a read-only report of the tested SP8YA while in standby:

````markdown
## aiotemescal device report

aiotemescal 0.4.0, Python 3.14.10, Linux x86_64

### Findings

- Model: SP8YA
- Firmware (main / micom / Chromecast): 2407090 / 2207202 / 1.56.310669
- Power state: not reported (no `b_powerstatus`), run with --guided to find out which fields change between on and standby
- Unique id: not reported (no `s_uuid`)
- Inputs offered: 0 (Wi-Fi), 1 (Bluetooth), 15 (Optical/HDMI ARC), 6 (HDMI), 19 (USB2)
- Sound modes offered: 19 (AI Sound Pro), 0 (Standard), 7 (Cinema), 20 (Clear Voice), 21 (Sports), 6 (Music), 22 (Game), 14 (Bass Blast), 5 (User), 15 (Dolby Atmos), 23 (unknown)
- Sound modes without a name in aiotemescal: 23
- Current input: 4 (Optical)
- No answer to: `MAC_INFO_DEV`

<details><summary>Full state</summary>

```text
# current
(shortened: one line per message, for all nine messages)
FUNC_VIEW_INFO: {"ai_func_list": [0, 1, 15, 6, 19], "b_connect": false, "i_curr_func": 4, "s_spk_bt_name": "<redacted>"}
PRODUCT_INFO: {"i_model_no": 0, "i_model_type": 0, "i_network_type": 1, "s_model_name": "SP8YA"}
```

</details>
````

### Add a device page

To document a model, copy [`docs/devices/_template.md`](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/_template.md)
to `docs/devices/lg-<model>.md`, fill it from the report and your observations,
and add a row to the table above. [`docs/devices/lg-sp8ya.md`](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/lg-sp8ya.md)
is an example.

### Test against your device

If you clone the repository, the [live tests](#tests) check the client against
a real device: `make test-live` is read-only, `make test-actions` changes
settings and restores them, and `make test-power-cycle` needs you to unplug the
device.

## Future work

### Devices without power control

Some soundbars, like the [SP8YA](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/lg-sp8ya.md#power), do not
implement power control: they never report `b_powerstatus` and ignore
`set_power()` without answering. The client currently sends the command
anyway, and an application cannot tell whether it did anything. This needs
to be handled:

- tell whether a device supports power control, from whether it reports
  `b_powerstatus`, so that applications can hide their power button;
- where it is reliable, follow the power state from other fields, such as
  `b_connect` on the SP8YA (only confirmed with the TV as the source so far).

Reports from other models (see [Contributing](#contributing)) are needed to
know which models are affected and which fields can be trusted.

### Unknown inputs and sound modes

The input and sound mode tables come from python-temescal and stop at the
models it knew. The [SP8YA](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/lg-sp8ya.md#inputs-and-sound-modes)
offers sound mode 23, which has no name yet; applications show it as unknown.
Its name has to be found, for example as shown in the LG app, and added to
`equalisers` in `const.py`, along with any index reported by other models.
The report lists these indices under "without a name in aiotemescal".

### Support for more models

Only the SP8YA has been tested, and the client assumes every model behaves the
same. Supporting more models means:

- turning the reports people send (see [Contributing](#contributing)) into
  test fixtures, by loading the state of a report into the fake soundbar of
  the tests, so that the behaviour of each model stays covered without the
  device;
- telling applications what a model supports, starting with power control
  (see above), instead of each application finding out by itself;
- completing the input and sound mode tables (see above).

### Power loss detection outside Linux

On macOS and Windows the client keeps the keepalive settings of the operating
system, so a device that loses power can go unnoticed for up to two hours (see
[Power loss detection](#power-loss-detection)). Both systems have equivalents
of the Linux options: `TCP_KEEPALIVE`, `TCP_KEEPINTVL` and `TCP_KEEPCNT` on
macOS, the `SIO_KEEPALIVE_VALS` ioctl on Windows. Neither has
`TCP_USER_TIMEOUT`, so commands sent to a device that just lost power may take
longer to fail.

### Identity from mDNS

Some devices give no stable identifier over the protocol: the SP8YA never
reports `s_uuid` and does not answer `MAC_INFO_DEV`. They do advertise one over
mDNS, as `LG_SMART_AUDIO-<uuid>._lg-smart-device._tcp.local.` with the UUID and
the IPv4 address in the TXT record. A helper that reads the UUID and the
address from such an announcement would spare each application from parsing
it.

### Stream desynchronisation

The client looks for the marker byte of the next frame and skips anything
else. On 2026-11-07 a long run of `skipping byte` debug messages was logged
with the SP8YA: the client had lost the start of a frame and skipped its
content byte by byte until it found a marker, which may also have been a byte
inside the frame rather than the start of the next one. The cause is not
known. It should be investigated, and reconnecting may be safer than searching
the stream for the next frame.

## Credits

The heavy lifting was done by [Matthew Garrett](https://github.com/mjg59), who
wrote [python-temescal](https://github.com/google/python-temescal) and made the
protocol usable from Python. The encryption key and IV, the message names and
the equaliser and function tables of this library all come from that work,
along with the additions of its contributors Berni Moses, teldri and
tomasrollo. aiotemescal only adds an asyncio client around them.

## License

Apache 2.0. Derived from python-temescal, Copyright 2018 Google LLC, also
licensed under Apache 2.0. The files taken from it say so in their header.
