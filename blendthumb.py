# -*- coding: utf-8 -*-
"""Витяг вбудованої мініатюри з .blend — лише стандартна бібліотека Python 3.14."""

from __future__ import annotations

import struct
import zlib

_MAX_LOGICAL = 1 << 20      # стеля на розібраний логічний потік
_MAX_COMPRESSED = 1 << 22   # стеля на прочитані з диска байти (захист від бомби)
_CHUNK = 8192               # оптимум: zstd-.blend віддає мініатюру з одного читання
_MAX_DIM = 4096
_MAX_PIXELS = 1 << 22


class _Reader:
    """Перші N байтів логічного потоку: raw / zstd / gzip. Рахує прочитане з диска."""

    def __init__(self, fh):
        self.fh = fh
        self.bytes_read = 0
        self.buf = bytearray()
        self._eof = False
        head = self._raw(4)
        self._pending = head
        if head[:4] == b"\x28\xb5\x2f\xfd":
            from compression import zstd
            self.kind, self._dec = "zstd", zstd.ZstdDecompressor()
        elif head[:2] == b"\x1f\x8b":
            self.kind = "gzip"
            self._dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
        else:
            self.kind, self._dec = "raw", None

    def _raw(self, n):
        b = self.fh.read(n)
        self.bytes_read += len(b)
        if not b:
            self._eof = True
        return b

    def _next_input(self, need):
        if self._pending:
            c, self._pending = self._pending, b""
            return c
        if self._eof or self.bytes_read >= _MAX_COMPRESSED:
            return b""
        # нестиснений файл читаємо рівно стільки, скільки бракує
        return self._raw(need if self._dec is None else _CHUNK)

    def _needs_input(self):
        if self.kind == "zstd":
            return self._dec.needs_input
        return not self._dec.unconsumed_tail

    def _decode(self, data, need):
        if self.kind == "zstd":
            return self._dec.decompress(data, max_length=need)
        tail = self._dec.unconsumed_tail
        return self._dec.decompress(tail + data if tail else data, need)

    def ensure(self, n):
        n = min(n, _MAX_LOGICAL)
        while len(self.buf) < n:
            need = n - len(self.buf)
            out = b""
            if self._dec is not None and not self._needs_input():
                out = self._decode(b"", need)        # злити внутрішній буфер
            if not out:
                chunk = self._next_input(need)
                if not chunk:
                    break
                out = chunk if self._dec is None else self._decode(chunk, need)
            self.buf += out
        return len(self.buf)


def _parse_header(h):
    """-> (offset_першого_блоку, розмір_BHead, endian, 'old'|'new') або None."""
    if len(h) < 12 or h[:7] != b"BLENDER":
        return None
    b7 = h[7:8]
    if b7 in (b"_", b"-"):                          # класичний 12-байтовий (Blender <= 4.4)
        ptr = 4 if b7 == b"_" else 8
        endian = h[8:9]
        if endian not in (b"v", b"V") or not h[9:12].isdigit():
            return None
        return 12, 4 + 4 + ptr + 4 + 4, "<" if endian == b"v" else ">", "old"
    if b7.isdigit() and h[8:9].isdigit():           # новий: BLENDER17-01v0502 (Blender 5.x)
        hdr = int(h[7:9])
        if not (12 <= hdr <= 64) or len(h) < hdr:
            return None
        if h[9:10] not in (b"_", b"-"):
            return None
        endian = h[12:13]
        if endian not in (b"v", b"V"):
            return None
        return hdr, 32, "<" if endian == b"v" else ">", "new"
    return None


def _png(w, h, rgba, flip=True):
    """RGBA, нижній рядок першим (як в ImBuf) -> PNG-байти."""
    stride = w * 4
    raw = bytearray()
    for y in (range(h - 1, -1, -1) if flip else range(h)):
        raw.append(0)                                # filter 0 = None
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def blend_thumbnail(path, _flip=True, _stats=None):
    """(width, height, png_bytes) або None. На вміст файлу виняток не кидає."""
    try:
        with open(path, "rb") as fh:
            r = _Reader(fh)
            if r.ensure(64) < 12:
                return None
            parsed = _parse_header(bytes(r.buf[:64]))
            if not parsed:
                return None
            off, bh_size, endian, flavour = parsed
            if flavour == "new":
                bh = struct.Struct(endian + "4siQQq")          # code sdna old len nr
                pick = 3
            else:
                ptr = 4 if r.buf[7:8] == b"_" else 8
                bh = struct.Struct(endian + "4si" + ("I" if ptr == 4 else "Q") + "ii")
                pick = 1                                       # code len old sdna nr
            if bh.size != bh_size:
                return None

            for _ in range(64):                                # TEST — серед перших блоків
                if r.ensure(off + bh.size) < off + bh.size:
                    return None
                t = bh.unpack_from(r.buf, off)
                code, blen = t[0], t[pick]
                if not 0 <= blen <= _MAX_LOGICAL:
                    return None
                if code == b"TEST":
                    need = off + bh.size + 8
                    if r.ensure(need) < need:
                        return None
                    w, h = struct.unpack_from(endian + "ii", r.buf, off + bh.size)
                    if not (0 < w <= _MAX_DIM and 0 < h <= _MAX_DIM):
                        return None
                    if w * h > _MAX_PIXELS or blen != (2 + w * h) * 4:
                        return None
                    end = off + bh.size + blen
                    if r.ensure(end) < end:
                        return None
                    px = bytes(r.buf[off + bh.size + 8:end])
                    if _stats is not None:
                        _stats.update(file_bytes_read=r.bytes_read, logical_bytes=end,
                                      container=r.kind, flavour=flavour)
                    return w, h, _png(w, h, px, flip=_flip)
                if code in (b"GLOB", b"DNA1", b"ENDB") or code[:1] == b"\x00":
                    return None            # TEST пишеться перед GLOB — далі його немає
                off += bh.size + blen
            return None
    except Exception:
        return None
