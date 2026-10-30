# aiotemescal

Asyncio client for LG soundbars and Wi-Fi speakers, speaking the "temescal"
protocol used by the LG Wi-Fi Speaker app (TCP port 9741).

It is a rewrite of [python-temescal](https://github.com/google/python-temescal)
that is meant for devices which come and go, for example a soundbar powered
through a smart plug:

- the connection is kept open in the background and re-established with an
  exponential backoff;
- a heartbeat detects half-open connections left by a power cut;
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

The heartbeat periodically asks for `PRODUCT_INFO` when the device has been
quiet; on some models this lights up the front display.

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
make test-power-cycle TEMESCAL_HOST=192.168.1.127  # asks you to unplug and replug it
```

`TEMESCAL_PORT` overrides the default port 9741.

## Device behaviour

Notes gathered on an SP8YA:

- The device must be turned on at least once using the remote or HDMI CEC to
  join the Wi-Fi network.
- During the first boot, ping can reach 5 s, then it goes below 10 ms.
- When powering on, it consumes 11 W for a few minutes, then about 4 W
  continuously, even when "turned off" with the remote or HDMI CEC.

## License

Apache 2.0. Derived from python-temescal, Copyright 2018 Google LLC.
