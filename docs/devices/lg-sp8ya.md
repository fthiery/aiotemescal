# LG SP8YA

What was learned on one SP8YA. It may or may not apply to other models.

| | |
| --- | --- |
| Firmware (main / micom / Chromecast) | 2407090 / 2207202 / 1.56.310669 (`UPDATE_VIEW_INFO`) |
| Connection to the TV | HDMI eARC |
| Chromecast | built in |
| Power | through a smart plug, sometimes cut |

## Identification and startup

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
  [power loss detection](../../README.md#power-loss-detection) relies on.

## Inputs and sound modes

- Inputs offered (`ai_func_list`): 0 (Wi-Fi), 1 (Bluetooth), 15 (Optical/HDMI
  ARC), 6 (HDMI), 19 (USB2). The current input is often one that is not in
  that list: 20 (E-ARC) when on, 4 (Optical) in standby.
- Sound modes offered (`ai_eq_list`): 19, 0, 7, 20, 21, 6, 22, 14, 5, 15 and
  23. Mode 23 has no name in aiotemescal yet.

## Daily restart

Expect a short disconnection every night. It restarts by itself once a day:
on the four nights observed, between about 04:00 and 04:20 local time. It
leaves the network for about 20 s, then refuses connections for a few more
seconds while it boots, and the client is connected again about 30 s after the
connection was lost. The Chromecast built into the soundbar drops at the same
moment, so the restart comes from the device, not from the client. An
application that shows whether the device is connected will show it as
unavailable during that time.

## Internet access

Do not cut the soundbar off from the internet. It keeps working for a while
without it, but on 2026-11-08, after its router blocked its internet access
(but not the local network), it left the network as soon as the TV was turned
off. A few minutes later it went to full standby (0 W instead of the usual
4 W network standby). When the TV was turned back on, it answered ping again,
but it refused connections on port 9741 and did not wake up with the TV. Once
its internet access was restored, it opened port 9741 within seconds and the
client reconnected without any action. Nothing the client does can work
around this: the device has to be reachable on the internet, presumably by the
Google servers the built-in Chromecast checks.

`C4A_SETTING_INFO` is not a reliable sign of this: asking for it always
returns `i_agree: 0`, with or without internet, while the messages the device
pushes by itself report `i_agree: 1`. Its `s_timezone`, when asked for, often
contains a fragment of the previous message instead of a time zone.

## Power

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
