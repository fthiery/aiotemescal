# Derived from python-temescal by Matthew Garrett, Copyright 2018 Google LLC,
# licensed under the Apache License, Version 2.0. Rewritten for asyncio by
# Florent Thiéry.

"""Constants of the temescal protocol."""

DEFAULT_PORT = 9741

KEY = b"T^&*J%^7tr~4^%^&I(o%^!jIJ__+a0 k"
IV = b"'%^Ur7gy$~t+f)%@"

MSG_C4A_SETTING_INFO = "C4A_SETTING_INFO"
MSG_EQ_VIEW_INFO = "EQ_VIEW_INFO"
MSG_FUNC_VIEW_INFO = "FUNC_VIEW_INFO"
MSG_MAC_INFO_DEV = "MAC_INFO_DEV"
MSG_PLAY_INFO = "PLAY_INFO"
MSG_PRODUCT_INFO = "PRODUCT_INFO"
MSG_SETTING_VIEW_INFO = "SETTING_VIEW_INFO"
MSG_SPK_LIST_VIEW_INFO = "SPK_LIST_VIEW_INFO"
MSG_UPDATE_VIEW_INFO = "UPDATE_VIEW_INFO"

# Indexed by the i_curr_eq / ai_eq_list values reported by the device
equalisers = [
    "Standard",
    "Bass",
    "Flat",
    "Boost",
    "Treble and Bass",
    "User",
    "Music",
    "Cinema",
    "Night",
    "News",
    "Voice",
    "ia_sound",
    "Adaptive Sound Control",
    "Movie",
    "Bass Blast",
    "Dolby Atmos",
    "DTS Virtual X",
    "Bass Boost Plus",
    "DTS X",
    "AI Sound Pro",
    "Clear Voice",
    "Sports",
    "Game",
]

# Indexed by the i_curr_func / ai_func_list values reported by the device
functions = [
    "Wi-Fi",
    "Bluetooth",
    "Portable",
    "Aux",
    "Optical",
    "CP",
    "HDMI",
    "ARC",
    "Spotify",
    "Optical2",
    "HDMI2",
    "HDMI3",
    "LG TV",
    "Mic",
    "Chromecast",
    "Optical/HDMI ARC",
    "LG Optical",
    "FM",
    "USB",
    "USB2",
    "E-ARC",
]

stream_types = ["Unknown0", "Google Cast", "Unknown2", "Unknown3", "Spotify Connect"]

play_control_states = ["Playing", "Stopped/Paused"]
