"""地図タイルの PNG を読むだけの最小限のデコーダ(標準ライブラリのみ)。"""

from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class Image:
    def __init__(self, width: int, height: int, color_type: int, rows: list, palette: bytes, alpha: bytes):
        self.width = width
        self.height = height
        self._color_type = color_type
        self._rows = rows
        self._palette = palette
        self._alpha = alpha

    def rgba(self, x: int, y: int) -> tuple:
        row = self._rows[y]
        if self._color_type == 6:
            return tuple(row[x * 4 : x * 4 + 4])
        if self._color_type == 2:
            r, g, b = row[x * 3 : x * 3 + 3]
            return (r, g, b, 255)
        if self._color_type == 3:
            i = row[x]
            a = self._alpha[i] if i < len(self._alpha) else 255
            return (self._palette[i * 3], self._palette[i * 3 + 1], self._palette[i * 3 + 2], a)
        if self._color_type == 0:
            g = row[x]
            return (g, g, g, 255)
        g, a = row[x * 2 : x * 2 + 2]
        return (g, g, g, a)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> list:
    rows = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        kind = raw[pos]
        line = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif kind == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + (left + prev[i]) // 2) & 255
        elif kind == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up_left = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 255
        elif kind != 0:
            raise ValueError(f"unknown PNG filter: {kind}")
        rows.append(line)
        prev = line
    return rows


def decode(data: bytes) -> Image:
    if data[:8] != SIGNATURE:
        raise ValueError("not a PNG")
    pos = 8
    idat = bytearray()
    palette = b""
    alpha = b""
    width = height = depth = color_type = interlace = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            alpha = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if width is None:
        raise ValueError("PNG without IHDR")
    if depth != 8 or interlace != 0 or color_type not in CHANNELS:
        raise ValueError(f"unsupported PNG: depth={depth} color_type={color_type} interlace={interlace}")
    bpp = CHANNELS[color_type]
    rows = _unfilter(zlib.decompress(bytes(idat)), height, width * bpp, bpp)
    return Image(width, height, color_type, rows, palette, alpha)
