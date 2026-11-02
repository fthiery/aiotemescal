# Derived from python-temescal by Matthew Garrett, Copyright 2018 Google LLC,
# licensed under the Apache License, Version 2.0. Rewritten for asyncio by
# Florent Thiéry.

"""Framing and encryption of temescal messages.

A frame is a 0x10 marker, a big-endian 32-bit length and an AES-256-CBC
encrypted, PKCS#7 padded JSON document. Key and IV are fixed by the protocol.
"""

import json
import struct
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import IV, KEY
from .exceptions import TemescalProtocolError

FRAME_MARKER = 0x10
LENGTH_SIZE = 4
BLOCK_SIZE = 16


def _cipher() -> Cipher[modes.CBC]:
    return Cipher(algorithms.AES(KEY), modes.CBC(IV))


def encode_frame(payload: dict[str, Any]) -> bytes:
    """Return the frame carrying the given message."""
    padder = padding.PKCS7(BLOCK_SIZE * 8).padder()
    padded = padder.update(json.dumps(payload).encode()) + padder.finalize()
    encryptor = _cipher().encryptor()
    body = encryptor.update(padded) + encryptor.finalize()
    return bytes([FRAME_MARKER]) + struct.pack(">I", len(body)) + body


def decode_length(data: bytes) -> int:
    """Return the body length announced in a frame header."""
    return struct.unpack(">I", data)[0]


def decode_body(body: bytes) -> dict[str, Any]:
    """Return the message carried by a frame body."""
    if not body or len(body) % BLOCK_SIZE:
        raise TemescalProtocolError(f"Invalid body length {len(body)}")
    decryptor = _cipher().decryptor()
    decrypted = decryptor.update(body) + decryptor.finalize()
    # Lenient unpadding: only the pad length is checked, like the original library
    pad = decrypted[-1]
    if not 1 <= pad <= BLOCK_SIZE:
        raise TemescalProtocolError(f"Invalid padding {pad}")
    try:
        message = json.loads(decrypted[:-pad])
    except ValueError as err:
        raise TemescalProtocolError(f"Invalid JSON: {err}") from err
    if not isinstance(message, dict):
        raise TemescalProtocolError(f"Unexpected message {message!r}")
    return message
