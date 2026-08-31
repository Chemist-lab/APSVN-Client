# -*- coding: utf-8 -*-
"""APSVN.exe — запускач для Windows. Запуск: python make_launcher.py

ЧОМУ НЕ PyInstaller. Він дав би exe на ~7 МБ (усередині цілий Python), тобто
третину ваги всієї програми заради обгортки, яка лише передає керування. І
такі файли антивіруси чіпляють постійно — для роздачі по студії це щоденна
морока.

Замість цього беремо готовий запускач із distlib, який лежить у кожному pip:
101 КБ, тих самих байтів, що в кожному встановленому пакеті з консольною
командою, — антивірусам він знайомий. Формат простий і задокументований:
    сам exe + рядок «#!шлях-до-python» + zip з __main__.py

ВІДНОСНИЙ ШЛЯХ У ШЕБАНГУ ПРАЦЮЄ — перевірено дослідом, бо від цього залежало
все: збірку розпаковують невідомо куди, і абсолютний шлях, зашитий на нашій
машині, вказував би в нікуди. `#!runtime\\pythonw.exe` розв'язується від теки
самого запускача.

Іконку вставляємо через UpdateResource — це звичайний Win32, без сторонніх
інструментів. Порядок важливий: спершу іконка, потім дописування шебанга й
zip. Навпаки не можна — EndUpdateResource переписує файл і зрізав би все, що
дописано за межами PE.
"""
import ctypes
import glob
import io
import os
import struct
import subprocess
import sys
import zipfile
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ICO = os.path.join(HERE, "apsvn.ico")
OUT = os.path.join(HERE, "APSVN.exe")

RT_ICON = 3
RT_GROUP_ICON = 14
LANG = 0x0409                       # en-US; Провідник бере будь-яку


def find_stub():
    """Запускач із distlib. w64 — віконний варіант: без чорної консолі."""
    roots = [os.path.join(os.path.dirname(os.__file__), "site-packages"),
             os.path.join(sys.prefix, "Lib", "site-packages")]
    for r in roots:
        for name in ("w64.exe", "w32.exe"):
            hit = glob.glob(os.path.join(r, "pip", "_vendor", "distlib", name))
            if hit:
                return hit[0]
    raise SystemExit("не знайшов w64.exe у pip/_vendor/distlib")


def read_ico(path):
    """.ico -> список (width, height, planes, bits, data)."""
    b = io.open(path, "rb").read()
    _, kind, n = struct.unpack("<HHH", b[:6])
    if kind != 1:
        raise SystemExit("це не .ico")
    out = []
    for i in range(n):
        w, h, _c, _r, planes, bits, size, off = struct.unpack(
            "<BBBBHHII", b[6 + 16 * i:6 + 16 * (i + 1)])
        out.append((w or 256, h or 256, planes, bits, b[off:off + size]))
    return out


def set_icon(exe, images):
    """Замінити іконку у вже готовому exe засобами самої Windows."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.BeginUpdateResourceW.restype = wintypes.HANDLE
    k.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k.UpdateResourceW.restype = wintypes.BOOL
    k.UpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, wintypes.WORD,
                                  wintypes.LPVOID, wintypes.DWORD]
    k.EndUpdateResourceW.restype = wintypes.BOOL
    k.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]

    # Тип ресурсу задається числом, замаскованим під вказівник — так вимагає
    # MAKEINTRESOURCE. Окрема функція, щоб не плутати з іменем-рядком.
    def res(n):
        return ctypes.cast(ctypes.c_void_p(n), wintypes.LPCWSTR)

    # СТИРАЄМО ВСІ РЕСУРСИ (другий аргумент True), а не додаємо свої поверх.
    #
    # Спершу було інакше: наша група діставала номер 1, рідна в запускача —
    # 101, і за порядком у каталозі наша мала б вигравати. Не виграла: Windows
    # мовчки показувала логотип Python, не повідомляючи ні про що. Видаляти ж
    # чужі записи поштучно не вийшло — UpdateResource не дає стерти й додати
    # той самий номер за один захід, і додавання падає.
    #
    # Стерти все тут безпечно, і це варто пояснити. Запускач — процес, який
    # живе частку секунди й не має жодного вікна: маніфест із DPI йому ні до
    # чого (вікно малює наш pythonw зі своїм маніфестом), а відомості про
    # версію в його властивостях однаково були б чужі — від distlib.
    h = k.BeginUpdateResourceW(exe, True)
    if not h:
        raise OSError("BeginUpdateResource: %d" % ctypes.get_last_error())

    grp = struct.pack("<HHH", 0, 1, len(images))
    for i, (w, ht, planes, bits, data) in enumerate(images, start=1):
        if not k.UpdateResourceW(h, res(RT_ICON), res(i), LANG,
                                 data, len(data)):
            raise OSError("UpdateResource(icon %d)" % i)
        grp += struct.pack("<BBBBHHIH",
                           0 if w >= 256 else w, 0 if ht >= 256 else ht,
                           0, 0, planes or 1, bits or 32, len(data), i)

    # Група має id 1: Провідник показує ту групу, чий ідентифікатор найменший,
    # а саме її запускач і використовує.
    if not k.UpdateResourceW(h, res(RT_GROUP_ICON), res(1), LANG,
                             grp, len(grp)):
        raise OSError("UpdateResource(group)")
    if not k.EndUpdateResourceW(h, False):
        raise OSError("EndUpdateResource: %d" % ctypes.get_last_error())


# Те, що виконається всередині програми. Шлях рахуємо від САМОГО ЗАПУСКАЧА, а
# не від поточної теки: у Провіднику вона довільна, а закріплений на панелі
# ярлик узагалі стартує з системної.
MAIN = '''import os, sys, runpy
here = os.path.dirname(os.path.abspath(sys.argv[0]))
sys.path.insert(0, here)
sys.path.insert(0, os.path.join(here, "vendor"))
os.chdir(here)
runpy.run_path(os.path.join(here, "app.py"), run_name="__main__")
'''


def build():
    if not os.path.isfile(ICO):
        print("немає apsvn.ico — роблю")
        subprocess.run([sys.executable, os.path.join(HERE, "make_icon.py")],
                       cwd=HERE, check=True)

    stub = find_stub()
    with open(OUT, "wb") as o:
        o.write(io.open(stub, "rb").read())

    set_icon(OUT, read_ico(ICO))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("__main__.py", MAIN)

    with open(OUT, "ab") as o:
        o.write(b"#!runtime\\pythonw.exe\r\n")
        o.write(buf.getvalue())

    print("APSVN.exe — %d байт (запускач %s)"
          % (os.path.getsize(OUT), os.path.basename(stub)))


if __name__ == "__main__":
    build()
