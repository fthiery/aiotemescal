# LG <model>

<!--
Copy this file to docs/devices/lg-<model>.md (lower case) and fill it from
`aiotemescal report HOST --guided`. Write down what you observed, with dates
and numbers where you have them, and say when something is a guess. Remove the
sections you have nothing for.
-->

What was learned on one <model>. It may or may not apply to other models.

| | |
| --- | --- |
| Firmware (main / micom / Chromecast) | from the report |
| Connection to the TV | HDMI eARC, HDMI ARC, optical, none… |
| Chromecast | built in or not |
| Power | always plugged in, smart plug… |

## Identification and startup

- What `PRODUCT_INFO` reports, whether `s_uuid` is reported and whether
  `MAC_INFO_DEV` is answered (see the findings of the report).
- How it shows up on the network (mDNS service name, host name), if known.
- How long port 9741 takes to open after the device is powered.

## Inputs and sound modes

Offered inputs and sound modes from the report, and any index reported as
"without a name in aiotemescal", with the name the LG app shows for it.

## Disconnections

Anything that makes the device leave the network by itself: daily restarts,
standby without network, internet access needed…

## Power

- Whether `b_powerstatus` is reported.
- Whether `set_power()` works (`--try-power`).
- Which fields change between on and standby (the "On and standby" table of the
  report), and the power draw in each state if you can measure it.

## Raw state

The `Full state` block of the report, in the same form as on the
[SP8YA page](lg-sp8ya.md#raw-state), saying whether the device was on or in
standby. Check that names and addresses are redacted.
