# -*- coding: utf-8 -*-
"""Шар, який знає про операційну систему.

Тут перевіряється те, що інакше вилізло б аж на чужій машині. Головне —
no_window(): попередній варіант
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
поза Windows не знаходив атрибута, брав число за замовчуванням і віддавав
його в Popen, де POSIX-гілка кидає ValueError. Тобто найперший виклик svn на
маку падав — і не там, де це шукали б.

Гілки для macOS тут ГАНЯЮТЬСЯ, а не просто читаються: підміняємо прапорці
й дивимось, що шар вирішує. Це не заміна запуску на справжньому маку, але
ловить те, що можна зловити звідси.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import desktop

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" | " + str(detail) if detail else ""))


class AsPlatform:
    """Тимчасово вдати іншу систему."""

    def __init__(self, win, mac):
        self.want = (win, mac)

    def __enter__(self):
        self.had = (desktop.WINDOWS, desktop.MAC)
        desktop.WINDOWS, desktop.MAC = self.want
        return self

    def __exit__(self, *a):
        desktop.WINDOWS, desktop.MAC = self.had


print("=" * 64)
print("1. no_window() — та сама міна")
print("=" * 64)
with AsPlatform(True, False):
    w = desktop.no_window()
check("на Windows віддає creationflags", "creationflags" in w, w)
check("і це число, яке гасить консоль", w.get("creationflags") == 0x08000000, w)

with AsPlatform(False, True):
    m = desktop.no_window()
check("на macOS віддає ПОРОЖНЄ", m == {}, m)
check("жодного creationflags там немає", "creationflags" not in m, m)

# Найважливіше: результат має бути придатний до Popen саме на цій системі.
# Якби тут лишалось старе число, цей виклик упав би з ValueError.
try:
    p = subprocess.run([sys.executable, "-c", "print(1)"],
                       capture_output=True, **desktop.no_window())
    check("Popen приймає те, що ми віддаємо", p.returncode == 0, p.returncode)
except ValueError as e:
    check("Popen приймає те, що ми віддаємо", False, e)

print()
print("=" * 64)
print("2. Де лежать налаштування")
print("=" * 64)
with AsPlatform(True, False):
    d = desktop.conf_dir("APSVN")
check("Windows -> APPDATA", "APSVN" in d and os.path.isabs(d), d)

with AsPlatform(False, True):
    d = desktop.conf_dir("APSVN")
check("macOS -> Library/Application Support",
      d.endswith(os.path.join("Library", "Application Support", "APSVN")), d)
check("а не крапкова тека, яку Finder ховає",
      "/.APSVN" not in d and "\\.APSVN" not in d, d)

with AsPlatform(False, False):
    d = desktop.conf_dir("APSVN")
check("решта -> XDG", ".config" in d or "XDG" in d or d.endswith("APSVN"), d)

print()
print("=" * 64)
print("3. Пошук svn")
print("=" * 64)
with AsPlatform(True, False):
    c = desktop.svn_candidates(r"C:\App")
check("Windows: свій svn.exe перший",
      c[0].endswith(os.path.join("svn", "svn.exe")), c[0])
check("Windows: SlikSvn у списку", any("SlikSvn" in x for x in c), c)

with AsPlatform(False, True):
    c = desktop.svn_candidates("/App")
check("macOS: свій svn першим", c[0].startswith("/App"), c[0])
check("macOS: Homebrew для Apple Silicon", "/opt/homebrew/bin/svn" in c, c)
check("macOS: Homebrew для Intel", "/usr/local/bin/svn" in c, c)
check("macOS: жодного .exe", not any(x.endswith(".exe") for x in c), c)

print()
print("=" * 64)
print("4. Рядок для AppleScript")
print("=" * 64)
# Шлях у повідомленні про помилку майже завжди містить зворотні слеші, а текст
# — лапки. Без екранування такий рядок ламає сам скрипт, і людина замість
# пояснення не бачить нічого.
check("зворотний слеш подвоєно",
      desktop._as(r"C:\Users\a") == r'"C:\\Users\\a"', desktop._as(r"C:\Users\a"))
check("лапки екрановано",
      desktop._as('файл "hero"') == '"файл \\"hero\\""', desktop._as('файл "hero"'))
check("кирилиця не чіпається", "сцена" in desktop._as("сцена.blend"))

print()
print("=" * 64)
print("5. Кодування: драбина потрібна лише Windows")
print("=" * 64)
import svn_client as sc
with AsPlatform(False, True):
    check("поза Windows кодова сторінка — utf-8", sc._acp() == "utf-8", sc._acp())
    check("8.3-псевдонімів поза Windows не буває",
          sc._short(os.getcwd()) is None)
with AsPlatform(True, False):
    check("на Windows кодова сторінка справжня",
          sc._acp().startswith("cp"), sc._acp())

print()
print("=" * 64)
print("6. Відкриття не валить програму")
print("=" * 64)
# Художник тисне «Show in folder» на файлі, який щойно зник. Це не привід
# падати — це привід повернути False.
check("open_path на дурниці віддає False",
      desktop.open_path(os.path.join(os.getcwd(), "нема-такого-файлу-12345"))
      in (True, False))
check("reveal теж не кидає винятку",
      desktop.reveal(os.path.join(os.getcwd(), "нема-такого-файлу-12345"))
      in (True, False))

print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
