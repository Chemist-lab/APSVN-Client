# -*- coding: utf-8 -*-
"""Які ресурси лежать у .exe. Потрібно рівно для того, щоб їх прибрати.

ЧОМУ НЕ EnumResourceNamesW. Він вимагає зворотного виклику з Python, а під
3.14 такий виклик валить процес із «_PyThreadState_Attach: non-NULL old
thread state». Читати таблицю самим — надійніше й, як виявилось, коротше за
боротьбу з тим падінням.

ЩО МИ ТУТ ШУКАЄМО І ЧОМУ ЦЕ ВАЖЛИВО. У каталозі ресурсів PE записи йдуть у
суворому порядку: спершу ті, що названі РЯДКОМ, потім ті, що номером.
Провідник бере першу-ліпшу групу іконок — тобто рядкову. Через це наша група
з номером 1 програвала рідній групі запускача, і exe показував логотип Python,
хоч наша іконка вже лежала всередині. Дізнатися ім'я тієї групи можна лише
прочитавши таблицю.
"""
import struct


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def resource_names(path, want_type):
    """Імена ресурсів заданого типу: рядок або int.

    want_type — число (3 = RT_ICON, 14 = RT_GROUP_ICON).
    """
    b = open(path, "rb").read()
    if b[:2] != b"MZ":
        return []
    pe = _u32(b, 0x3C)
    if b[pe:pe + 4] != b"PE\0\0":
        return []

    n_sections = _u16(b, pe + 6)
    opt_size = _u16(b, pe + 20)
    opt = pe + 24
    magic = _u16(b, opt)
    # PE32 тримає таблицю каталогів на 96 байті, PE32+ — на 112
    dd = opt + (96 if magic == 0x10B else 112)
    res_rva = _u32(b, dd + 8 * 2)          # каталог №2 — ресурси
    if not res_rva:
        return []

    sect = pe + 24 + opt_size
    base = None
    for i in range(n_sections):
        s = sect + 40 * i
        va, vsz = _u32(b, s + 12), _u32(b, s + 8)
        raw = _u32(b, s + 20)
        if va <= res_rva < va + max(vsz, 1):
            base = raw - va                # RVA -> зсув у файлі
            break
    if base is None:
        return []

    def entries(off):
        n_named = _u16(b, off + 12)
        n_id = _u16(b, off + 14)
        out = []
        for i in range(n_named + n_id):
            e = off + 16 + 8 * i
            name, data = _u32(b, e), _u32(b, e + 4)
            if name & 0x80000000:          # ім'я-рядок
                p = base + res_rva + (name & 0x7FFFFFFF)
                ln = _u16(b, p)
                nm = b[p + 2:p + 2 + ln * 2].decode("utf-16-le")
            else:
                nm = name
            out.append((nm, data))
        return out

    root = base + res_rva
    for nm, data in entries(root):
        if nm != want_type:
            continue
        if not (data & 0x80000000):        # має бути підкаталог
            return []
        return [n for n, _ in entries(base + res_rva + (data & 0x7FFFFFFF))]
    return []


if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    for label, t in (("RT_ICON", 3), ("RT_GROUP_ICON", 14),
                     ("RT_VERSION", 16), ("RT_MANIFEST", 24)):
        print("%-14s %s" % (label, resource_names(p, t) or "—"))
