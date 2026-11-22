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
  `audiocast.local`. That UUID is not reported over the protocol, so the
  device offers no identifier that matches it, nor any other that stays the
  same when its IP address changes.
- When it boots, port 9741 opens 10 to 32 s after the device first answers
  ping, and connections are refused until then.
- It answers TCP keepalive probes and keeps an idle connection open without
  any application traffic (tested for 3 minutes), which is what
  [power loss detection](../../README.md#power-loss-detection) relies on.
- Its Wi-Fi link loses a packet now and then: about one ping in 10 to 30
  failed while the device was fine. With two keepalive probes, a short gap was
  enough to close a healthy connection, which is why the client allows five.
- Right after going to standby, it can take more than a second to answer a
  keepalive probe. On 2026-11-22, in two reports out of three, the connection
  was closed 6 to 10 s after going to standby, with the remote or the TV, and
  the client reconnected at once. `TCP_USER_TIMEOUT` was then 4 s, which made a
  single probe unanswered for a second enough to close the connection; it is
  now 10 s, so that all five probes run. During a 3-minute watch the same day,
  every probe was answered within a second and the connection held through
  each power change. With 10 s, a full report the same day (five standbys, with
  the remote and the TV) did not lose the connection once.

## Inputs and sound modes

- Inputs offered (`ai_func_list`): 0 (Wi-Fi), 1 (Bluetooth), 15 (Optical/HDMI
  ARC), 6 (HDMI), 19 (USB2). The current input is often one that is not in
  that list: 20 (E-ARC) when on, 4 (Optical) in standby.
- Sound modes offered (`ai_eq_list`): 19, 0, 7, 20, 21, 6, 22, 14, 5, 15 and
  23. Mode 23 shows as "Sound Share" on the display of the soundbar (the LG
  app shows "Synchronisé avec la télévision" in French), and is named so in
  aiotemescal.

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
- `set_power(False)` (the `b_powerkey` key) does nothing, and no power command
  gets an answer. `set_power(True)` sent after a standby by remote does turn
  it on (its display shows OPT), but so does any other request (see below), so
  this is not a working power command. The LG app has no power button for it
  either.

The client therefore reports `reports_power` as `False` for it, and never
checks it when it is silent (see the README, "Silent devices").

### What it reports by itself

It turns on and off by following the TV over HDMI eARC, with `b_auto_power`
enabled in `SETTING_VIEW_INFO`. Its power draw is 11-12 W on and about 4 W in
network standby. The report of 2026-11-22 recorded what it sends by itself:

- **Turning on with the TV** is reported. It sends `FUNC_VIEW_INFO` with
  `i_curr_func: 4` (Optical), then `20` (E-ARC) with `b_connect: true`, each
  followed by `SPK_LIST_VIEW_INFO` and `PLAY_INFO`. Turning the TV on while
  the soundbar is already on sends only the `20` (E-ARC) part.
- **Being woken by a request** sends `FUNC_VIEW_INFO` with `i_curr_func: 4`
  about half a second later, followed by `SPK_LIST_VIEW_INFO` and `PLAY_INFO`
  (`b_connect` is `true` if the TV is on). This was seen after a standby with
  the remote and with the TV, so a client can at least tell that it woke the
  soundbar.
- **Going to standby with the TV** sends nothing, twice in that report: no
  message has `b_connect: false`. On 2026-11-08 a `FUNC_VIEW_INFO` with
  `b_connect: false` and `i_curr_func: 4` had been seen on each change, but its
  internet access was blocked that day (see [Internet access](#internet-access)).
- **Turning on or off with the remote** sends nothing, and when asked, its
  state is the same on and in standby (`b_connect: false`, `i_curr_func: 4`).
  Right after being turned on with the remote, it did not answer
  `SPK_LIST_VIEW_INFO` within 2 s, in two reports out of two (the first also
  missed `FUNC_VIEW_INFO`), presumably while it starts.

So turning on with the TV can be detected, but going to standby cannot be
detected over the protocol, and neither can any change made with the remote.
The power draw of a smart plug is the only reliable sign observed so far.

### Waking on requests

Any request turns it on when it is in network standby, whichever way it went
there, so its state cannot be read in standby either. On 2026-11-21, a
connection was opened without sending anything, which did not wake it, then a
single `SPK_LIST_VIEW_INFO` was sent: it turned the soundbar on, on its optical
input, after a standby with the remote and after a standby following the TV.
Each of `PRODUCT_INFO`, `UPDATE_VIEW_INFO`, `EQ_VIEW_INFO`, `SETTING_VIEW_INFO`,
`PLAY_INFO`, `FUNC_VIEW_INFO` and `SPK_LIST_VIEW_INFO` was also tried alone,
with the same result. The reports of 2026-11-22 found the same, with the remote
and with the TV. On 2026-11-08, with its internet access blocked, it had stayed
in standby when asked.

When its power comes back (smart plug turned on), it starts on, before any
request, so the client does not wake it in that case.

Since the client asks for the whole state on every connection, a reconnection
while it is in standby turns it on: after its [daily restart](#daily-restart),
at night, or after a Wi-Fi loss. Whether it then goes back to standby by itself
without the TV has not been checked.

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
