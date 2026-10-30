"""Tests for the temescal framing."""

import pytest

from aiotemescal import TemescalProtocolError
from aiotemescal.protocol import (
    FRAME_MARKER,
    LENGTH_SIZE,
    decode_body,
    decode_length,
    encode_frame,
)


@pytest.mark.parametrize(
    "message",
    [
        {"cmd": "get", "msg": "EQ_VIEW_INFO"},
        {"msg": "SETTING_VIEW_INFO", "data": {"s_user_name": "Salon " * 60}},
    ],
)
def test_round_trip(message: dict) -> None:
    frame = encode_frame(message)

    assert frame[0] == FRAME_MARKER
    length = decode_length(frame[1 : 1 + LENGTH_SIZE])
    assert length == len(frame) - 1 - LENGTH_SIZE
    assert decode_body(frame[1 + LENGTH_SIZE :]) == message


def test_known_frame() -> None:
    """Frames must match the ones produced by the original temescal library."""
    frame = encode_frame({"cmd": "get", "msg": "EQ_VIEW_INFO"})

    assert frame.hex() == (
        "1000000030"
        "3e44007588dd47d48234ff2cb7a30f8e"
        "6b66fd3cac9240205e2922befebe2c6d"
        "901913ddeb4c589ea3080417699f5ebf"
    )


@pytest.mark.parametrize(
    "body",
    [b"", b"x" * 15, bytes(16)],
    ids=["empty", "not_block_aligned", "bad_padding"],
)
def test_invalid_body(body: bytes) -> None:
    with pytest.raises(TemescalProtocolError):
        decode_body(body)
