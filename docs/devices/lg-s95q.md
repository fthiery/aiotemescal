# LG S95Q

**Second-hand.** Nothing on this page was observed with aiotemescal. It comes
from what skynet01 wrote while working on an S95Q, in
[home-assistant/core#189520](https://github.com/home-assistant/core/pull/189520)
and in the comments of his library
[lg-bartalk](https://github.com/skynet01/lg-bartalk/blob/v0.1.3/src/lg_bartalk/__init__.py).
A report (`aiotemescal report HOST --guided`) would confirm or correct it.

| | |
| --- | --- |
| Firmware (main / micom / Chromecast) | unknown |
| Connection to the TV | unknown |
| Chromecast | unknown |
| Power | unknown |

## Power

- It reports `b_powerstatus`, so its power state can be followed.
- `set_power()` (`b_powerkey`) is believed to work on it: skynet01 added the
  power control to Home Assistant
  ([home-assistant/core#127022](https://github.com/home-assistant/core/pull/127022))
  and reported that it worked on his device, without naming the model at the
  time.

## Disconnections

- **Silent stalls.** After it is turned on or off by hand, it "can stop sending
  updates without closing the TCP connection, while commands still work". TCP
  keepalive cannot notice this, since the device still acknowledges. The client
  checks a device that reported being on and stays silent (README, "Silent
  devices"), which is meant for this case.
- **Waking up when queried in standby.** lg-bartalk does not query it while it
  is known to be off, because "querying a unit in standby can wake it". This
  has not been confirmed. The `--guided` report asks it for its state in
  standby and then asks whether it is still in standby (README, "Waking devices
  in standby").
