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

The client therefore reports `reports_power` as `False` for it, and never
checks it when it is silent (see the README, "Silent devices"). Asking it for
its state while in standby does not wake it up: it was asked several times on
2026-11-08 and stayed in standby.

Comparing the full state in both cases, only these two fields change.
`b_connect` is therefore the only hint of the power state, but it has only
been observed with the TV as the source, not with Bluetooth or Wi-Fi playback.

## Raw state

What the device answers to each message, as collected by `aiotemescal report`
on 2026-11-08, in network standby (firmware above). Names and addresses are
redacted. `null` means the device did not answer.

```json
{
  "C4A_SETTING_INFO": {
    "i_agree": 0,
    "s_timezone": "d"
  },
  "EQ_VIEW_INFO": {
    "ai_eq_list": [19, 0, 7, 20, 21, 6, 22, 14, 5, 15, 23],
    "i_bass": 5,
    "i_curr_eq": 0,
    "i_treble": 5,
    "merdian_eq_list": [6]
  },
  "FUNC_VIEW_INFO": {
    "ai_func_list": [0, 1, 15, 6, 19],
    "b_connect": false,
    "i_curr_func": 4,
    "s_spk_bt_name": "<redacted>"
  },
  "MAC_INFO_DEV": null,
  "PLAY_INFO": {
    "b_support_play_ctrl": true,
    "i_duration": 0,
    "i_play_ctrl": 0,
    "i_position": 0,
    "i_stream_type": 0
  },
  "PRODUCT_INFO": {
    "i_model_no": 0,
    "i_model_type": 0,
    "i_network_type": 1,
    "s_model_name": "SP8YA"
  },
  "SETTING_VIEW_INFO": {
    "b_auto_power": true,
    "b_auto_vol": false,
    "b_avsmrm_status": false,
    "b_drc": false,
    "b_enable_dialog": false,
    "b_neuralx": false,
    "b_night_time": false,
    "b_nighttime_enable": true,
    "b_rear": false,
    "b_set_device_name": false,
    "b_soundbarmode": false,
    "b_support_avsmrm": true,
    "b_support_diag": true,
    "b_tv_remote": true,
    "b_wow_connect": false,
    "i_av_sync": 0,
    "i_calibration_status": 0,
    "i_center_level": 6,
    "i_center_max": 6,
    "i_center_min": -6,
    "i_curr_eq": 0,
    "i_dialog_level": 0,
    "i_dialog_max": 6,
    "i_dialog_min": 0,
    "i_rear_level": 3,
    "i_rear_max": 6,
    "i_rear_min": -6,
    "i_top_level": 6,
    "i_top_max": 6,
    "i_top_min": -6,
    "i_woofer_level": 15,
    "i_woofer_max": 6,
    "i_woofer_min": -15,
    "s_ipv4_addr": "<redacted>",
    "s_ipv6_addr": "<redacted>",
    "s_user_name": "<redacted>"
  },
  "SPK_LIST_VIEW_INFO": {
    "b_avsmrm_status": false,
    "b_func_pictogram": true,
    "b_mute": false,
    "b_soundbarmode": false,
    "b_spotify_connect": false,
    "b_support_avsmrm": true,
    "b_update": false,
    "b_wow_connect": false,
    "i_calibration_status": 0,
    "i_curr_func": 4,
    "i_vol": 15,
    "i_vol_max": 40,
    "i_vol_min": 0,
    "s_user_name": "<redacted>"
  },
  "UPDATE_VIEW_INFO": {
    "b_update": false,
    "i_progress": 0,
    "o_server_ver": {},
    "o_system_ver": {
      "s_c4a": "1.56.310669",
      "s_main": "2407090",
      "s_micom": "2207202"
    },
    "s_region": "df"
  }
}
```

Note the corrupted `s_timezone` in `C4A_SETTING_INFO` (see
[Internet access](#internet-access)). When on, the only differences are those
listed under [Power](#power).
