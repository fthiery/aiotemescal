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
  `TCP_USER_TIMEOUT`, without any application traffic;
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
connected, and `request()` raises `TemescalTimeoutError` when no answer arrives.

Every message received from the device is delivered to the `subscribe()`
callbacks, including answers to requests and unsolicited status updates.

## Reconnection

While the device is unreachable, the client retries with a backoff that grows
from 1 to 5 s. If you learn by other means that the device is back, call
`reconnect_now()` to retry right away; it does nothing while connected.
`set_host()` changes the address of the device and retries right away.

## Power loss detection

A device that loses power stops acknowledging TCP packets. The client
configures the socket so that the kernel closes such a connection after about
7 s when idle (keepalive probes after 5 s of silence, every second, two
missed), or 3 s after a command that is not acknowledged. These options exist on
Linux; on other systems the defaults of the OS apply and detection can take much
longer.

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
make test-power-cycle TEMESCAL_HOST=192.168.1.127  # asks you to unplug and replug it
```

`TEMESCAL_PORT` overrides the default port 9741.

## Tested devices

| Model | Firmware (main / micom / Chromecast) |
| --- | --- |
| LG SP8YA | 2407090 / 2207202 / 1.56.310669 |

The versions are those reported in `UPDATE_VIEW_INFO`.

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
