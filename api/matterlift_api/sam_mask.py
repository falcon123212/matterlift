"""Decoder for SAM 3.1 `one_bit` masks (request metadata.mask_encoding = "one_bit").

A port of decodeRaster from Meta's @meta-sam/parser 0.1.0 (dist/mask-codec.js): a length-prefixed
base85 payload holding an adaptive binary range code, each pixel coded in a 12-bit context made of
its already-decoded neighbours. The raster covers the record's box: H rows x W columns.
Docs: https://dev.meta.ai/docs/sam/reading-segmentation
"""
from __future__ import annotations

import numpy as np

_EXCLUDED = set('"\\,;<>|')
_ALPHABET = "".join(chr(c) for c in range(0x21, 0x7F) if chr(c) not in _EXCLUDED)
_VALUE = {c: i for i, c in enumerate(_ALPHABET[:85])}
_M = 0xFFFFFFFF
_TOP = 1 << 24
_BOTTOM = 1 << 16
_INCREMENT = 14
_COUNT_LIMIT = 4096
_PAD = 2


class MaskError(ValueError):
    pass


def _unpack(payload: str) -> bytes:
    """5-digit base85 length prefix, then 4-byte groups as 5 digits, short tail."""
    try:
        digits = [_VALUE[c] for c in payload]
    except KeyError as e:
        raise MaskError(f"invalid character {e}") from None
    if len(digits) < 5:
        raise MaskError("missing length prefix")
    length = 0
    for d in digits[:5]:
        length = length * 85 + d
    rem = length % 4
    if len(digits) != 5 + (length // 4) * 5 + (rem + 1 if rem else 0):
        raise MaskError("length does not match prefix")
    out = bytearray()
    src = 5
    for _ in range(length // 4):
        v = 0
        for d in digits[src : src + 5]:
            v = v * 85 + d
        out += v.to_bytes(4, "big")
        src += 5
    if rem:
        v = 0
        for i in range(5):
            v = v * 85 + (digits[src + i] if i < rem + 1 else 84)
        out += v.to_bytes(4, "big")[:rem]
    return bytes(out)


def decode_one_bit(payload: str, height: int, width: int) -> np.ndarray:
    """`payload` includes the leading "!" marker. Returns a (height, width) bool array."""
    if not payload.startswith("!"):
        raise MaskError("one_bit payloads start with '!' (request metadata.mask_encoding=one_bit)")
    data = _unpack(payload[1:])
    if len(data) < 4:
        raise MaskError("missing finalization")
    pos = 4
    code = int.from_bytes(data[:4], "big")
    low, rng = 0, _M

    counts = [1] * (2 << 12)
    pw = width + 2 * _PAD
    padded = bytearray(pw * (height + _PAD))
    out = np.zeros(height * width, dtype=np.uint8)
    n = len(data)

    for y in range(height):
        row = (y + _PAD) * pw + _PAD
        for x in range(width):
            p = row + x
            q = p - pw
            e = q - pw
            ctx = (padded[p - 1] | (padded[p - 2] << 1) | (padded[q - 2] << 2) | (padded[q - 1] << 3)
                   | (padded[q] << 4) | (padded[q + 1] << 5) | (padded[q + 2] << 6)
                   | (padded[e - 2] << 7) | (padded[e - 1] << 8) | (padded[e] << 9)
                   | (padded[e + 1] << 10) | (padded[e + 2] << 11))
            off = ctx << 1
            zero, one = counts[off], counts[off + 1]
            total = zero + one
            scaled = rng // total
            if scaled == 0:
                raise MaskError("invalid coding state")
            value = ((code - low) & _M) // scaled
            if value >= total:
                value = total - 1
            if value < zero:
                bit, cum, freq = 0, 0, zero
            else:
                bit, cum, freq = 1, zero, one
            low = (low + scaled * cum) & _M
            rng = scaled * freq
            while True:
                if (low ^ ((low + rng) & _M)) < _TOP:
                    pass
                elif rng < _BOTTOM:
                    rng = ((-low) & _M) & (_BOTTOM - 1)
                else:
                    break
                if pos >= n:
                    raise MaskError("payload ended before decoding completed")
                code = ((code << 8) | data[pos]) & _M
                pos += 1
                low = (low << 8) & _M
                rng = (rng << 8) & _M
            padded[p] = bit
            out[y * width + x] = bit
            counts[off + bit] += _INCREMENT
            if counts[off] + counts[off + 1] >= _COUNT_LIMIT:
                counts[off] = counts[off] >> 1 or 1
                counts[off + 1] = counts[off + 1] >> 1 or 1
    return out.reshape(height, width).astype(bool)
