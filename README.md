# aiotemescal

Asyncio client for LG soundbars and Wi-Fi speakers, speaking the "temescal"
protocol used by the LG Wi-Fi Speaker app (TCP port 9741).

It is a rewrite of [python-temescal](https://github.com/google/python-temescal),
archived since 2023, for devices that are only intermittently present on the
network, for example a soundbar powered through a smart plug. It sends the same
messages and reads the answers the same way, so models that worked with
python-temescal should keep working. It is used by the
[LG Soundbars](https://www.home-assistant.io/integrations/lg_soundbar)
integration of Home Assistant.

Features:

- the connection is kept open in the background and re-established with a
  backoff;
- a power loss is noticed within seconds, without application traffic (on
  Linux);
- after each connection, the whole state is requested before the connection is
  reported, so a device that comes back is never shown with its old state;
- requests can be awaited for their answer.

## Contents

- [Usage](#usage)
- [Connection](#connection)
- [Power state](#power-state)
- [Command line](#command-line)
- [Tests](#tests)
- [Devices](#devices)
- [Contributing](#contributing)
- [Future work](#future-work)
- [Credits](#credits)
- [License](#license)

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
connected or does not acknowledge them, and `request()` raises
`TemescalTimeoutError` when no answer arrives. Every message received from the
device, answers and unsolicited updates alike, is delivered to the
`subscribe()` callbacks.

## Connection

### Reconnection

While the device is unreachable, the client retries with a backoff that grows
from 1 to 5 s. `reconnect_now()` retries right away, for example when the
device announces itself; it does nothing while connected. `set_host()` changes
the address and retries right away.

On each connection, the client asks for `SPK_LIST_VIEW_INFO`,
`FUNC_VIEW_INFO`, `EQ_VIEW_INFO`, `SETTING_VIEW_INFO` and `PLAY_INFO`, and
reports the connection once they are answered or timed out. Some devices wake
up when asked for their state in standby (see
[Future work](#waking-devices-in-standby)).

### Power loss detection

A device that loses power stops acknowledging TCP packets. The client
configures the socket so that the kernel closes such a connection after about
10 s, whether it is idle (keepalive probes after 5 s of silence, every second,
five missed) or a command is not acknowledged. Five probes rather than fewer,
so that a Wi-Fi link that loses a packet now and then, or a device slow to
answer right after going to standby, does not close a healthy connection.
`TCP_USER_TIMEOUT` is set to the same 10 s, since the kernel also uses it to
give up on keepalive: shorter, a single unanswered probe would close the
connection.

Commands wait for the device to acknowledge them at the TCP level, so a command
sent to a device that just lost power raises `TemescalConnectionError` instead
of returning as if it had been delivered.

This relies on Linux socket options (`TCP_USER_TIMEOUT` only exists on Linux).
Elsewhere, the defaults of the operating system apply, often two hours of
silence before the first keepalive probe. Home Assistant OS is not affected.

### Silent devices

Some devices stop sending updates without closing the connection, while still
acknowledging at the TCP level, which keepalive cannot notice. When a device
that reported being on has sent nothing for `idle_timeout` seconds (30 by
default), the client asks it for `SPK_LIST_VIEW_INFO`, and reconnects if no
answer arrives. Devices in standby and devices that do not report their power
state are never asked, since asking can wake them.

## Power state

`power_on` is the last power state the device reported (`b_powerstatus`), or
`None` while it is unknown. `reports_power` is `None` until the first answer
to `SPK_LIST_VIEW_INFO`, then `False` if that answer had no `b_powerstatus`,
and `True` as soon as one is seen. Devices that never report it generally
ignore `set_power()` too, so an application can hide its power control when
`reports_power` is `False`.

## Command line

```
uvx aiotemescal 192.168.1.15 -v                  # print every message and connection change
uvx aiotemescal report 192.168.1.15 -o report.md # describe the device (see Contributing)
```

## Tests

```
make test                                          # unit tests, against a fake soundbar
make test-live TEMESCAL_HOST=192.168.1.127         # read-only tests against a real device
make test-actions TEMESCAL_HOST=192.168.1.127      # changes and restores settings, input and power
make test-power-cycle TEMESCAL_HOST=192.168.1.127  # asks you to unplug and replug it, twice
make test-all TEMESCAL_HOST=192.168.1.127          # all of the above in a single run
```

`TEMESCAL_PORT` overrides the default port 9741.

## Devices

Models differ in what they report, what they support and when they leave the
network. What was learned on each is in its device page:

- [LG SP8YA](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/lg-sp8ya.md)
- [LG S95Q](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/lg-s95q.md)
- [other models](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/other-models.md),
  reported by others but not tested with aiotemescal

## Contributing

A report from your device is the most useful contribution, even if everything
works.

### Report your device

With [uv](https://docs.astral.sh/uv/), from a machine on the same network as
the device, while at the device. Close the LG app and temporarily disable the
LG Soundbars integration of Home Assistant, or any other client of the device:
they query it, which can turn it on and hides what it sends by itself.

```
uvx aiotemescal report 192.168.1.15 -o report.md
```

The report always does every step, so that reports can be compared:

- it reads the state: what the device reports, the inputs and sound modes it
  offers, and the messages it does not answer;
- it asks you to put the device in standby, then to turn it on, first with its
  remote, then with the TV if the device follows it. For each change, it
  records what the device sends by itself, compares the state on and in
  standby, asks whether reading the state in standby turned it on, and
  concludes whether the power state can be followed;
- it selects each sound mode that has no name yet, asks which name the display
  shows, then restores the current mode.

An example session with an SP8YA, which any request turns on in standby (what
you type is after `[y/n]`; the other prompts only wait for Enter):

```text
$ uvx aiotemescal report 192.168.1.15 -o report.md
Run the report at the device, with its remote: it asks you to put the device in standby and to turn it on, with its remote and then with the TV, and selects each sound mode without a name before restoring the current one.
Keep the LG app closed and the Home Assistant integration disabled during the report: they query the device, which interferes with what the report observes.
Does the device turn on and off with the TV (HDMI ARC or eARC, optical)? [y/n] y
Make sure the device is on, then press Enter.
Put the device in standby with its remote or its own button, and wait until it is in standby (display off), then press Enter.
Is it still in standby now that its state was read? [y/n] n
Put it in standby again with its remote or its own button, wait until it is done, then press Enter.
Turn the device on with its remote or its own button, then press Enter.
Make sure the TV is on and the device is on with it, then press Enter.
Turn the TV off, and wait until the device follows it into standby (display off), then press Enter.
Is it still in standby now that its state was read? [y/n] n
Turn the TV on then off again, so that the device follows it into standby, wait until it is done, then press Enter.
Turn the TV on, and wait until the device follows it, then press Enter.
Report written to report.md
```

`-o` writes the Markdown report to a file, which keeps it apart from the
questions asked on the terminal. Addresses, UUIDs and names are replaced with
`<redacted>` (`--no-redact` keeps them). Behaviours that only show up over
time are not caught by the report: watch the device with
`uvx aiotemescal HOST -v` for a while and paste the relevant part.

Then [open an issue](https://github.com/fthiery/aiotemescal/issues/new?template=device_report.md)
with the report and anything it cannot see, such as how the device is
connected to the TV.

### Add a device page

Copy [`docs/devices/_template.md`](https://github.com/fthiery/aiotemescal/blob/main/docs/devices/_template.md)
to `docs/devices/lg-<model>.md`, fill it from the report and your
observations, and add it to [Devices](#devices).

### Test against your device

The [live tests](#tests) check the client against a real device.

## Future work

### Devices without power control

`set_power()` sends the `b_powerkey` key from
[an unmerged python-temescal pull request](https://github.com/mjg59/python-temescal/pull/1),
also used by the Home Assistant integration since
[home-assistant/core#127022](https://github.com/home-assistant/core/pull/127022).
Some models ignore it, others only follow it one way, and the client cannot
tell. Applications need to know whether a device supports power control, and,
where it is reliable, its power state could be followed from other fields.

### Waking devices in standby

Some devices turn on when they receive any request in standby. Since the
client asks for the whole state on every connection, a reconnection while
such a device is in standby turns it on. Avoiding it would mean not asking for
the state on reconnection for these devices, and relying on what they report
by themselves, at the cost of a state that may be stale.

### Devices that go silent in standby

Some devices stop delivering updates after being turned off by hand, so the
next power-on is never reported. The [silent device](#silent-devices) check
only covers devices that are on. A fix could ask for the state a few seconds
after the device reports turning off, and reconnect if it does not answer.

### Unknown inputs and sound modes

The input and sound mode tables come from python-temescal. Indices reported by
newer models need names in `const.py`; the report lists them and asks for
their names.

### Support for more models

Turn device reports into test fixtures for the fake soundbar, so that each
model stays covered without the device, and tell applications what a model
supports instead of each finding out by itself.

### Power loss detection outside Linux

There, commands do not wait for the device to acknowledge them, and the
keepalive options are only set under their Linux names. Set the equivalent
options on macOS and Windows (such as `TCP_KEEPALIVE` on macOS) and test
there. Not a priority, since Home
Assistant runs on Linux.

### Identity from mDNS

Some devices give no stable identifier over the protocol but advertise one
over mDNS (`_lg-smart-device._tcp.local.`). A helper that reads it would spare
each application from parsing it.

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
