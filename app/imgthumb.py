# -*- coding: utf-8 -*-
"""Дешеві превʼю для .png/.jpg/.exr/.tga — тільки стандартна бібліотека."""

from __future__ import annotations

import base64
import os
import struct
import zlib
from itertools import accumulate

MAX_INLINE = 6 << 20        # більший PNG/JPEG у data: URI не заганяємо
THUMB = 256                 # цільова довша сторона для декодованих форматів


# ------------------------------------------------------------------ PNG вихід
def encode_png(w, h, rgb, alpha=False):
    n = 4 if alpha else 3
    stride = w * n
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


# --------------------------------------------------- 1. РОЗМІР з заголовка
def image_size(path, _head=None):
    """(width, height, kind) з перших кілобайтів або None."""
    try:
        b = _head if _head is not None else open(path, "rb").read(65536)
    except OSError:
        return None
    if b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR":
        w, h = struct.unpack_from(">II", b, 16)
        return w, h, "png"
    if b[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            seg = struct.unpack_from(">H", b, i + 2)[0]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack_from(">HH", b, i + 5)
                return w, h, "jpeg"
            if m == 0xDA:
                break
            i += 2 + seg
        return None
    if b[:4] == b"\x76\x2f\x31\x01":
        hdr = _exr_header(b)
        if hdr and "dataWindow" in hdr["attrs"]:
            x0, y0, x1, y1 = struct.unpack("<4i", hdr["attrs"]["dataWindow"][2])
            return x1 - x0 + 1, y1 - y0 + 1, "exr"
        return None
    if b[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack_from("<HH", b, 6)
        return w, h, "gif"
    if b[:2] == b"BM" and len(b) >= 26:
        w, h = struct.unpack_from("<ii", b, 18)
        return abs(w), abs(h), "bmp"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return None if len(b) < 30 else _webp_size(b)
    tga = _tga_header(b, os.path.getsize(path) if os.path.exists(path) else len(b))
    if tga:
        return tga["w"], tga["h"], "tga"
    return None


def _webp_size(b):
    if b[12:16] == b"VP8 ":
        w, h = struct.unpack_from("<HH", b, 26)
        return w & 0x3FFF, h & 0x3FFF, "webp"
    if b[12:16] == b"VP8L":
        v = struct.unpack_from("<I", b, 21)[0]
        return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1, "webp"
    if b[12:16] == b"VP8X":
        w = int.from_bytes(b[24:27], "little") + 1
        h = int.from_bytes(b[27:30], "little") + 1
        return w, h, "webp"
    return None


# --------------------------------------------------------------- 2. TGA
def _tga_header(b, fsize):
    """TGA не має магії — валідуємо поля. Повертає dict або None."""
    if len(b) < 18:
        return None
    idlen, cmap_type, imtype = b[0], b[1], b[2]
    if cmap_type not in (0, 1) or imtype not in (1, 2, 3, 9, 10, 11):
        return None
    cmap_len = struct.unpack_from("<H", b, 5)[0]
    cmap_bits = b[7]
    w, h = struct.unpack_from("<HH", b, 12)
    bpp, desc = b[16], b[17]
    if not (0 < w <= 32768 and 0 < h <= 32768):
        return None
    if bpp not in (8, 15, 16, 24, 32):
        return None
    if cmap_type == 0 and cmap_len:
        return None
    if cmap_type == 1 and cmap_bits not in (15, 16, 24, 32):
        return None
    px_off = 18 + idlen + (cmap_len * ((cmap_bits + 7) // 8) if cmap_type else 0)
    if imtype in (1, 2, 3) and fsize < px_off + w * h * (bpp // 8):
        return None                       # нестиснений TGA має бути щонайменше такий
    if fsize < px_off + 1:
        return None
    return {"w": w, "h": h, "bpp": bpp, "type": imtype, "px_off": px_off,
            "bottom_up": not (desc & 0x20), "right_left": bool(desc & 0x10),
            "cmap_type": cmap_type, "cmap_len": cmap_len, "cmap_bits": cmap_bits,
            "idlen": idlen}


def _tga_decode(path, target=THUMB):
    b = open(path, "rb").read()
    hd = _tga_header(b, len(b))
    if not hd or hd["cmap_type"]:                 # палітру не підтримуємо
        return None
    w, h, bpp, t = hd["w"], hd["h"], hd["bpp"], hd["type"]
    npx, i = bpp // 8, hd["px_off"]
    total = w * h
    if t in (2, 3):                                # нестиснений
        flat = b[i:i + total * npx]
        if len(flat) < total * npx:
            return None
    elif t in (10, 11):                            # RLE
        out = bytearray()
        need = total * npx
        while len(out) < need and i < len(b):
            p = b[i]
            i += 1
            cnt = (p & 0x7F) + 1
            if p & 0x80:
                out += b[i:i + npx] * cnt
                i += npx
            else:
                out += b[i:i + cnt * npx]
                i += cnt * npx
        if len(out) < need:
            return None
        flat = bytes(out[:need])
    else:
        return None

    k = max(1, max(w, h) // target)
    ow, oh = max(1, w // k), max(1, h // k)
    rgb = bytearray(ow * oh * 3)
    for oy in range(oh):
        sy = oy * k
        sy = (h - 1 - sy) if hd["bottom_up"] else sy      # TGA знизу вгору -> PNG згори
        base = sy * w * npx
        for ox in range(ow):
            o = base + (ox * k) * npx
            d = (oy * ow + ox) * 3
            if npx == 1:
                g = flat[o]
                rgb[d] = rgb[d + 1] = rgb[d + 2] = g
            else:                                          # TGA — BGR(A)
                rgb[d] = flat[o + 2]
                rgb[d + 1] = flat[o + 1]
                rgb[d + 2] = flat[o]
    return ow, oh, bytes(rgb)


# --------------------------------------------------------------- 3. EXR
_EXR_PIXSIZE = {0: 4, 1: 2, 2: 4}


def _exr_header(b):
    if b[:4] != b"\x76\x2f\x31\x01":
        return None
    ver = struct.unpack_from("<I", b, 4)[0]
    attrs, i = {}, 8
    try:
        while i < len(b):
            e = b.index(b"\x00", i)
            name = b[i:e]
            i = e + 1
            if not name:
                break
            e = b.index(b"\x00", i)
            atype = b[i:e].decode("ascii", "replace")
            i = e + 1
            size = struct.unpack_from("<i", b, i)[0]
            i += 4
            if not 0 <= size <= 1 << 20:
                return None
            attrs[name.decode("ascii", "replace")] = (atype, size, b[i:i + size])
            i += size
    except (ValueError, struct.error):
        return None
    return {"ver": ver, "attrs": attrs, "data_start": i,
            "tiled": bool(ver & 0x200), "deep": bool(ver & 0x800),
            "multipart": bool(ver & 0x1000)}


_XOR80 = bytes(i ^ 0x80 for i in range(256))
_AND255 = (255).__and__


def _unpredict(t):
    """t[j] = (t[j-1] + t[j] - 128) & 0xFF.

    Це префіксна сума за модулем 256 зі зсувом -128*j. Оскільки 128*j mod 256
    дорівнює 0 для парних j і 128 для непарних, а (x-128) mod 256 == x ^ 0x80,
    зсув зводиться до XOR 0x80 на непарних позиціях. Обидва кроки — на рівні C,
    без байтового циклу в Python (вдвічі швидше; звірено байт-у-байт з еталоном).
    """
    r = bytearray(map(_AND255, accumulate(t)))
    r[1::2] = r[1::2].translate(_XOR80)
    return bytes(r)


def _exr_unzip(raw, out_size):
    """ZIP/ZIPS: zlib + предиктор + деінтерлив (ImfZipCompressor)."""
    t = zlib.decompress(raw)
    if len(t) != out_size:
        return None
    t = _unpredict(t)
    half = (out_size + 1) // 2
    out = bytearray(out_size)
    out[0::2] = t[:half][:len(out[0::2])]
    out[1::2] = t[half:][:len(out[1::2])]
    return bytes(out)


def _exr_rle(raw, out_size):
    t, i = bytearray(), 0
    while i < len(raw) and len(t) < out_size:
        n = raw[i] - 256 if raw[i] > 127 else raw[i]
        i += 1
        if n < 0:
            t += raw[i:i + 1] * (-n + 1)
            i += 1
        else:
            t += raw[i:i + n + 1]
            i += n + 1
    if len(t) != out_size:
        return None
    t = _unpredict(bytes(t))
    half = (out_size + 1) // 2
    out = bytearray(out_size)
    out[0::2] = t[:half][:len(out[0::2])]
    out[1::2] = t[half:][:len(out[1::2])]
    return bytes(out)


_LUT = bytes(min(255, max(0, round(255.0 * ((i / 4095.0) ** (1 / 2.2))))) for i in range(4096))


def _tone(v):
    if v != v or v <= 0.0:            # NaN або <=0
        return 0
    if v >= 1.0:
        return 255
    return _LUT[int(v * 4095.0)]


def _exr_decode(path, target=THUMB, budget=8 << 20):
    """Тонемапнутий превʼю зі scanline-EXR: NO_COMPRESSION / RLE / ZIPS / ZIP."""
    fh = open(path, "rb")
    try:
        head = fh.read(1 << 16)
        hd = _exr_header(head)
        if not hd or hd["tiled"] or hd["deep"] or hd["multipart"]:
            return None
        a = hd["attrs"]
        if "dataWindow" not in a or "channels" not in a or "compression" not in a:
            return None
        x0, y0, x1, y1 = struct.unpack("<4i", a["dataWindow"][2])
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if not (0 < w <= 32768 and 0 < h <= 32768):
            return None
        comp = a["compression"][2][0]
        rows_per_block = {0: 1, 1: 1, 2: 1, 3: 16}.get(comp)
        if rows_per_block is None:
            return None                       # PIZ/PXR24/B44/DWA — не stdlib
        dec = {0: None, 1: _exr_rle, 2: _exr_unzip, 3: _exr_unzip}[comp]

        raw = a["channels"][2]                # chlist, уже за абеткою
        chans, j = [], 0
        while j < len(raw) and raw[j] != 0:
            e = raw.index(b"\x00", j)
            nm = raw[j:e].decode("ascii", "replace")
            pt, _, xs, ys = struct.unpack_from("<iBxxxii", raw, e + 1)
            if pt not in _EXR_PIXSIZE or xs != 1 or ys != 1:
                return None
            chans.append((nm, pt, _EXR_PIXSIZE[pt]))
            j = e + 1 + 16
        if not chans:
            return None
        by_name = {c[0]: n for n, c in enumerate(chans)}
        if {"R", "G", "B"} <= by_name.keys():
            pick = [by_name["R"], by_name["G"], by_name["B"]]
        elif "Y" in by_name:
            pick = [by_name["Y"]] * 3
        else:
            pick = [0, 0, 0]
        row_bytes = sum(w * c[2] for c in chans)
        offs = [0]
        for c in chans[:-1]:
            offs.append(offs[-1] + w * c[2])

        nblocks = (h + rows_per_block - 1) // rows_per_block
        need = 8 * nblocks
        while len(head) < hd["data_start"] + need:
            more = fh.read(max(1 << 16, hd["data_start"] + need - len(head)))
            if not more:
                return None
            head += more
        table = struct.unpack_from("<%dQ" % nblocks, head, hd["data_start"])

        k = max(1, max(w, h) // target)
        ow, oh = max(1, w // k), max(1, h // k)
        out = bytearray(ow * oh * 3)
        rowfmt = {0: struct.Struct("<%dI" % w), 1: struct.Struct("<%de" % w),
                  2: struct.Struct("<%df" % w)}
        cache, spent = {}, 0
        for oy in range(oh):
            sy = oy * k
            bi = sy // rows_per_block
            if bi >= nblocks:
                break
            if bi not in cache:
                if spent > budget:
                    break
                fh.seek(table[bi])
                hdr = fh.read(8)
                if len(hdr) < 8:
                    break
                _ycoord, dsize = struct.unpack("<ii", hdr)
                if not 0 < dsize <= (row_bytes * rows_per_block + 4096):
                    break
                blob = fh.read(dsize)
                spent += dsize + 8
                nrows = min(rows_per_block, h - bi * rows_per_block)
                want = row_bytes * nrows
                if dec is None or dsize == want:
                    plain = blob
                else:
                    try:
                        plain = dec(blob, want)
                    except zlib.error:
                        plain = None
                if plain is None or len(plain) < want:
                    break
                cache.clear()
                cache[bi] = plain
            plain = cache[bi]
            base = (sy - bi * rows_per_block) * row_bytes
            d0 = oy * ow * 3
            for comp_i, ci in enumerate(pick):
                pt = chans[ci][1]
                row = rowfmt[pt].unpack_from(plain, base + offs[ci])   # весь рядок разом
                if pt == 0:
                    vals = [v / 65535.0 for v in row[::k][:ow]]
                else:
                    vals = row[::k][:ow]
                d = d0 + comp_i
                for v in vals:
                    out[d] = _tone(v)
                    d += 3
        return ow, oh, bytes(out)
    except (OSError, struct.error, ValueError, zlib.error):
        return None
    finally:
        fh.close()


# ------------------------------------------------ 4. EXIF-мініатюра з JPEG
def jpeg_exif_thumbnail(path, budget=1 << 18):
    """Вбудована EXIF-мініатюра (зазвичай 160x120 JPEG) або None."""
    try:
        b = open(path, "rb").read(budget)
        if b[:3] != b"\xff\xd8\xff":
            return None
        i = 2
        while i + 4 <= len(b):
            if b[i] != 0xFF:
                return None
            m = b[i + 1]
            if m == 0xDA or m == 0xD9:
                return None
            seg = struct.unpack_from(">H", b, i + 2)[0]
            if m == 0xE1 and b[i + 4:i + 10] == b"Exif\x00\x00":
                tiff = i + 10
                bo = "<" if b[tiff:tiff + 2] == b"II" else ">"
                ifd0 = tiff + struct.unpack_from(bo + "I", b, tiff + 4)[0]
                n = struct.unpack_from(bo + "H", b, ifd0)[0]
                ifd1_off = struct.unpack_from(bo + "I", b, ifd0 + 2 + n * 12)[0]
                if not ifd1_off:
                    return None
                ifd1 = tiff + ifd1_off
                n1 = struct.unpack_from(bo + "H", b, ifd1)[0]
                start = length = None
                for e in range(n1):
                    p = ifd1 + 2 + e * 12
                    tag = struct.unpack_from(bo + "H", b, p)[0]
                    val = struct.unpack_from(bo + "I", b, p + 8)[0]
                    if tag == 0x0201:
                        start = tiff + val
                    elif tag == 0x0202:
                        length = val
                if start and length and start + length <= len(b):
                    jpg = b[start:start + length]
                    if jpg[:2] == b"\xff\xd8":
                        return jpg
                return None
            i += 2 + seg
        return None
    except (OSError, struct.error, IndexError):
        return None


# ------------------------------------------------------- 5. головний вхід
def preview_data_uri(path, max_inline=MAX_INLINE, target=THUMB):
    """data: URI, який вебвʼю покаже напряму, або None."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return None
    info = image_size(path, _head=head)
    kind = info[2] if info else None

    if kind in ("png", "gif", "webp", "bmp"):
        if size > max_inline:
            return None
        mime = {"png": "image/png", "gif": "image/gif",
                "webp": "image/webp", "bmp": "image/bmp"}[kind]
        with open(path, "rb") as f:
            return "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode())

    if kind == "jpeg":
        if size > max_inline:
            t = jpeg_exif_thumbnail(path)
            if t:
                return "data:image/jpeg;base64," + base64.b64encode(t).decode()
            return None
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()

    if kind == "exr":
        r = _exr_decode(path, target)
        if r:
            return "data:image/png;base64," + base64.b64encode(
                encode_png(r[0], r[1], r[2])).decode()
        return None

    if kind == "tga":
        r = _tga_decode(path, target)
        if r:
            return "data:image/png;base64," + base64.b64encode(
                encode_png(r[0], r[1], r[2])).decode()
        return None

    return None
