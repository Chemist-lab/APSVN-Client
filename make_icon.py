# -*- coding: utf-8 -*-
"""Іконка APSVN. Запуск: python make_icon.py -> apsvn.ico

ЧОМУ КОДОМ, А НЕ ФАЙЛОМ. Двійкова іконка в репозиторії — це те, чого ніхто не
може ані перезібрати, ані змінити на пів тону: щоб підправити відтінок,
потрібен той самий редактор, у тієї самої людини. Тут вона описана формулами,
тож переробити її може будь-хто, а git показує зміну як зміну коду.

Малюємо замок, бо вся програма про «зайняв файл — працюю — здав». І саме
замок читається на 16 пікселях, де слово APSVN перетворюється на сіру кашу.

Жодних бібліотек: фігури задаються відстанню до краю (signed distance), краї
згладжуються тією ж відстанню, PNG пишеться руками. Це той самий кодувальник,
що вже стоїть у imgthumb.py, — не хочеться тягнути Pillow заради одного файлу,
якого художник ніколи не побачить у процесі.
"""
import math
import struct
import zlib

# Кольори програми, ті самі, що в ui/style.css
TILE = (0x1D, 0x24, 0x30)          # плитка — колір виділеного рядка
LOCK = (0x4F, 0x8C, 0xFF)          # дужка й корпус — акцентний синій
HOLE = (0x14, 0x19, 0x22)          # отвір — трохи темніший за плитку

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _rounded_box(x, y, cx, cy, hw, hh, r):
    """Відстань до прямокутника із заокругленими кутами. Мінус — усередині."""
    dx = abs(x - cx) - (hw - r)
    dy = abs(y - cy) - (hh - r)
    ox, oy = max(dx, 0.0), max(dy, 0.0)
    return math.hypot(ox, oy) + min(max(dx, dy), 0.0) - r


def _ring(x, y, cx, cy, radius, half):
    """Відстань до кільця — з нього робиться дужка замка."""
    return abs(math.hypot(x - cx, y - cy) - radius) - half


def _circle(x, y, cx, cy, r):
    return math.hypot(x - cx, y - cy) - r


def _cover(d, px):
    """Відстань -> покриття 0..1. Згладжування шириною в один піксель.

    Без нього іконка на 16 px розсипається на сходинки, а саме цей розмір
    Провідник показує в списках найчастіше.
    """
    t = 0.5 - d / px
    return 0.0 if t <= 0 else (1.0 if t >= 1 else t)


def _over(dst, src, a):
    """Накласти колір із прозорістю на вже намальоване."""
    return tuple(int(round(s * a + d * (1 - a))) for s, d in zip(src, dst))


def render(size):
    """RGBA-байти іконки заданого розміру.

    Геометрія в частках від сторони, а не в пікселях: та сама формула дає і
    16, і 256, і пропорції не пливуть.
    """
    px = 1.0 / size                       # ширина пікселя в частках
    out = bytearray(size * size * 4)

    for iy in range(size):
        for ix in range(size):
            # центр пікселя
            x = (ix + 0.5) / size
            y = (iy + 0.5) / size

            # 1. плитка
            d_tile = _rounded_box(x, y, 0.5, 0.5, 0.46, 0.46, 0.21)
            a_tile = _cover(d_tile, px)
            if a_tile <= 0.0:
                continue                  # поза плиткою — лишається прозорим

            rgb = TILE

            # 2. дужка: верхня половина кільця над корпусом
            d_sh = _ring(x, y, 0.5, 0.475, 0.155, 0.045)
            if y > 0.475:                 # нижню половину відрізаємо
                d_sh = max(d_sh, y - 0.475)
            a = _cover(d_sh, px)
            if a > 0:
                rgb = _over(rgb, LOCK, a)

            # 3. корпус
            d_body = _rounded_box(x, y, 0.5, 0.655, 0.27, 0.185, 0.055)
            a = _cover(d_body, px)
            if a > 0:
                rgb = _over(rgb, LOCK, a)

            # 4. отвір під ключ — лише там, де є корпус
            d_hole = _circle(x, y, 0.5, 0.63, 0.062)
            a = _cover(d_hole, px)
            if a > 0 and d_body < 0:
                rgb = _over(rgb, HOLE, a)

            o = (iy * size + ix) * 4
            out[o] = rgb[0]
            out[o + 1] = rgb[1]
            out[o + 2] = rgb[2]
            out[o + 3] = int(round(255 * a_tile))
    return bytes(out)


def png(size, rgba):
    """RGBA -> PNG. Той самий формат, що й у imgthumb.encode_png."""
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)                     # фільтр рядка: жодного
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def dib(size, rgba):
    """RGBA -> DIB, як його чекають ресурси Windows.

    ЧОМУ НЕ PNG. У .ico-файлі PNG приймається будь-де, і спокуса зробити все
    однаково велика. Але ВСЕРЕДИНІ exe (ресурс RT_ICON) Windows читає PNG лише
    для розміру 256 — решту мусить бути DIB. Через це наша група іконок
    виявилась нечитаною, exe показував логотип запускача, і жодної помилки при
    цьому ніхто не видавав: просто мовчазний відкат на іншу групу.

    Формат старий і має дві незручності, обидві обов'язкові: висота в заголовку
    подвоєна (колір плюс маска), а рядки пікселів ідуть знизу вгору.
    """
    hdr = struct.pack("<IiiHHIIiiII",
                      40, size, size * 2, 1, 32, 0,
                      size * size * 4, 0, 0, 0, 0)
    body = bytearray()
    for y in range(size - 1, -1, -1):            # знизу вгору
        row = rgba[y * size * 4:(y + 1) * size * 4]
        for x in range(size):
            r, g, b, a = row[x * 4:x * 4 + 4]
            body += bytes((b, g, r, a))          # BGRA

    # Маска прозорості. Ми її не використовуємо — прозорість несе альфа-канал —
    # але поле обов'язкове, і рядки в ньому вирівнюються на 4 байти.
    stride = ((size + 31) // 32) * 4
    mask = bytes(stride * size)
    return hdr + bytes(body) + mask


def icns(sizes):
    """Іконка для macOS. Формат простий: 'icns', розмір, далі типізовані блоки.

    Робиться тут, а не на маку, з однієї причини: малюнок мусить бути ТОЙ САМИЙ.
    Дві іконки, намальовані окремо для двох систем, розходяться на першій же
    правці — і ніхто цього не помічає, бо ніхто не тримає обидві перед очима.

    Типи блоків — це просто домовлені чотирилітерні мітки для розмірів; усередині
    звичайний PNG, який macOS там приймає.
    """
    TYPES = {16: b"ic04", 32: b"ic05", 64: b"ic12",
             128: b"ic07", 256: b"ic08", 512: b"ic09"}
    body = b""
    for s in sizes:
        if s not in TYPES:
            continue
        data = png(s, render(s))
        body += TYPES[s] + struct.pack(">I", len(data) + 8) + data
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def ico(images):
    """Список (розмір, PNG) -> вміст .ico.

    Усі зображення кладемо як PNG, а не як BMP: Windows читає такі .ico з
    Vista, а BMP довелося б писати догори дриґом і з окремою маскою прозорості.
    """
    n = len(images)
    head = struct.pack("<HHH", 0, 1, n)   # reserved, type=icon, count
    entries, blob = b"", b""
    offset = 6 + 16 * n
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # 0 означає 256
            0 if size >= 256 else size,
            0, 0,                         # палітра, reserved
            1, 32,                        # площини, біт на піксель
            len(data), offset)
        blob += data
        offset += len(data)
    return head + entries + blob


if __name__ == "__main__":
    # 256 лишається PNG: у такому розмірі це втричі менший файл, і Windows
    # його там приймає. Решта — DIB, інакше exe покаже чужу іконку.
    imgs = [(s, png(s, render(s)) if s >= 256 else dib(s, render(s)))
            for s in SIZES]
    data = ico(imgs)
    with open("apsvn.ico", "wb") as fh:
        fh.write(data)
    # Той самий малюнок для шапки програми. Окремим файлом, а не data:URI в
    # HTML: інакше картинка живе двома копіями — у коді й у розмітці — і одна
    # з них рано чи пізно відстане від іншої.
    import os
    ui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
    if os.path.isdir(ui):
        with open(os.path.join(ui, "icon.png"), "wb") as fh:
            fh.write(png(64, render(64)))
        print("ui/icon.png — 64x64")

    mac = icns((16, 32, 64, 128, 256, 512))
    with open("apsvn.icns", "wb") as fh:
        fh.write(mac)
    print("apsvn.icns — %d байт" % len(mac))

    print("apsvn.ico — %d розмірів, %d байт" % (len(imgs), len(data)))
    for s, d in imgs:
        print("   %3d x %-3d  %5d байт" % (s, s, len(d)))
