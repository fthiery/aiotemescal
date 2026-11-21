# LG S95Q

What was learned on one S95Q, reported by skynet01: a guided report with
aiotemescal 0.5.0 on 2026-11-20 ([fthiery/aiotemescal#2](https://github.com/fthiery/aiotemescal/pull/2)),
and weeks of use with his library [lg-bartalk](https://github.com/skynet01/lg-bartalk)
([home-assistant/core#189520](https://github.com/home-assistant/core/pull/189520)).
It may or may not apply to other models.

| | |
| --- | --- |
| Model name (`PRODUCT_INFO`) | S95QR |
| Firmware (main / micom / Chromecast) | 2603241 / 2501151 / 1.56.310669 (`UPDATE_VIEW_INFO`) |
| Connection to the TV | HDMI eARC |
| Chromecast | built in |

## Identification

- `PRODUCT_INFO` reports `s_uuid`, along with `s_product_name: "WiFi Speaker"`,
  `s_product_id` and `s_country`. `MAC_INFO_DEV` and `C4A_SETTING_INFO` get no
  answer.
- `SPK_LIST_VIEW_INFO` also reports `i_year: 22`, and the Bluetooth name comes
  in `s_bt_name` rather than `s_spk_bt_name` as on the SP8YA.

## Inputs and sound modes

- Inputs offered (`ai_func_list`): 0 (Wi-Fi), 1 (Bluetooth), 15 (Optical/HDMI
  ARC), 6 (HDMI), 10 (HDMI2), 19 (USB2). The current input is 20 (E-ARC) when
  on with the TV.
- Sound modes offered (`ai_eq_list`): 19, 0, 7, 26, 21, 6, 22, 14, 5, 15, 23,
  24 and 25. Mode 23 is presumably "Sound Share", as on the SP8YA; modes 24 to 26
  have no name in aiotemescal yet.
- The volume goes from 0 to 100 (`i_vol_max`), against 40 on the SP8YA.

## Power

- It reports `b_powerstatus`, so `reports_power` is `True` and its power state
  can be followed.
- `set_power()` works both ways: `b_powerkey` false puts it in standby and true
  turns it back on, and each change is reported right away.
- During the guided report, the input was switched to HDMI, HDMI2, USB2 and
  then Wi-Fi before the soundbar went to standby by itself, so the comparison
  between on and standby mixes the input change with the power change: only
  `b_powerstatus` and `s_audio_source` (`" PCM "` to `"NO SIGNAL"`) can be
  attributed to standby. `b_connect` seems to follow the connection of the
  current input rather than the power state (it was `true` on Wi-Fi), and is
  not needed here since `b_powerstatus` is reported. A new run of the guided
  report, without changing input, would confirm it.
- It also pushes `DIAG_INFO` messages about the connection of its rear speakers
  and subwoofer (`b_rear_l_connected`, `b_rear_r_connected`,
  `b_woofer_connected`) while it turns on.

## Disconnections

- **Asking for its state in standby does not wake it up**, as checked by the
  guided report and over weeks of lg-bartalk asking for it about 5 s after
  every shutdown.
- **A connection that never sent a request does not receive the power-on
  update.** aiotemescal asks for the whole state on every connection, so it is
  not affected.
- **Silent sessions.** After being turned on or off by hand, it can stop
  sending updates without closing the TCP connection, while commands still
  work. aiotemescal checks a device that reported being on and stays silent
  (README, "Silent devices"). This was not exercised by the report, which uses
  a single connection without that check.
- **Dead session after some manual shutdowns.** Not every time, the connection
  stops delivering updates after the device is turned off by hand, and the
  next power-on is never reported. The silent device check does not cover
  devices in standby. lg-bartalk reconnected about 5 s after each off report
  and asked for the state once (README, Future work).
