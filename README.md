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

A device can also disconnect on its own; see [LG SP8YA](#lg-sp8ya) for the
cases observed on the tested soundbar.

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

| Model | Firmware (main / micom / Chromecast) |
| --- | --- |
| LG SP8YA | 2407090 / 2207202 / 1.56.310669 |

The versions are those reported in `UPDATE_VIEW_INFO`.

## LG SP8YA

What was learned on the tested SP8YA (firmware above), which may or may not
apply to other models.

### Identification and startup

- `PRODUCT_INFO` reports `s_model_name: "SP8YA"`. The device never reports
  `s_uuid` and does not answer `MAC_INFO_DEV`.
- It advertises itself over mDNS as
  `LG_SMART_AUDIO-<uuid>._lg-smart-device._tcp.local.`, with the UUID and the
  IPv4 address in the TXT record, under the generic host name
  `audiocast.local`.
- When it boots, port 9741 opens 10 to 32 s after the device first answers
  ping, and connections are refused until then.
- It answers TCP keepalive probes and keeps an idle connection open without
  any application traffic (tested for 3 minutes), which is what
  [Power loss detection](#power-loss-detection) relies on.

### Daily restart

Expect a short disconnection every night. It restarts by itself once a day:
on the four nights observed, between about 04:00 and 04:20 local time. It
leaves the network for about 20 s, then refuses connections for a few more
seconds while it boots, and the client is connected again about 30 s after the
connection was lost. The Chromecast built into the soundbar drops at the same
moment, so the restart comes from the device, not from the client. An
application that shows whether the device is connected will show it as
unavailable during that time.

### Internet access

Do not cut the soundbar off from the internet. It keeps working for a while
without it, but on 2026-11-08, after its router blocked its internet access
(but not the local network), it left the network as soon as the TV was turned
off. Just before, `C4A_SETTING_INFO` had reported `i_agree`
going from 1 to 0, so the built-in Chromecast seems to have reset. A few
minutes later the soundbar went to full standby (0 W instead of the usual
4 W network standby). When the TV was turned back on, it answered ping again,
but it refused connections on port 9741 and did not wake up with the TV. Once
its internet access was restored, it opened port 9741 within seconds, `i_agree`
went back to 1, and the client reconnected without any action. Nothing the
client does can work around this: the device has to be reachable on the
internet, at least by the Google servers the Chromecast checks.

### Power

It does not support remote power control:

- it never sends `b_powerstatus`, in any message, so its power state cannot be
  read directly;
- it ignores `set_power()` (the `b_powerkey` key) whether it is on or in
  standby, with either value, and sends no answer. The LG app has no power
  button for it either.

It turns on and off by following the TV over HDMI eARC, with `b_auto_power`
enabled in `SETTING_VIEW_INFO`. On each change it sends `FUNC_VIEW_INFO`
unprompted, followed by `SPK_LIST_VIEW_INFO` and `PLAY_INFO`:

| State | Power draw | `b_connect` | `i_curr_func` |
| --- | --- | --- | --- |
| On | 11-12 W | `True` | 20 (E-ARC) |
| Network standby | about 4 W | `False` | 4 (Optical) |

Comparing the full state in both cases, only these two fields change.
`b_connect` is therefore the only hint of the power state, but it has only
been observed with the TV as the source, not with Bluetooth or Wi-Fi playback.

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
