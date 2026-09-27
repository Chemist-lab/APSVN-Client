# -*- coding: utf-8 -*-
"""Який Blender відкриває .blend: версії, пошук на машині, запуск.

Справжній Blender тут не запускається: запуск перехоплюємо, а пошук на
цій машині лише звіряємо з диском — який саме Blender у кого стоїть, тест
знати не може.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import blender
import desktop

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_blender_")


def fake_exe(*parts):
    full = os.path.join(base, *parts)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(b"MZ")
    return full


print("=" * 64)
print("1. Версії: як їх пише студія, інсталятор і сам Blender")
print("=" * 64)
for raw, want in (("5.1", "5.1"), ("5.1.2", "5.1"), ("Blender 4.2 LTS", "4.2"),
                  ("blender.5.1", "5.1"), ("Blender 5.1", "5.1"), ("10.0", "10.0"),
                  ("5", None), ("", None), (None, None), ("latest", None)):
    check("%r -> %r" % (raw, want), blender.parse_version(raw) == want,
          blender.parse_version(raw))
check("4.10 новіша за 4.9", sorted(["4.10", "5.0", "4.9"], key=blender.vkey)
      == ["4.9", "4.10", "5.0"])
check("відповідь blender --version",
      blender.version_from_output("Blender 5.1.0\n\tbuild date: 2026-09-01\n") == "5.1")
check("…і LTS", blender.version_from_output("Blender 4.2.3 LTS\n") == "4.2")
check("…і не Blender — None", blender.version_from_output("Python 3.14") is None)
check("сторінка завантаження — саме цієї версії",
      blender.download_page("5.1.2") ==
      "https://download.blender.org/release/Blender5.1/")
check("без версії — загальна", blender.download_page(None) ==
      "https://www.blender.org/download/")
check("у адресу йдуть лише цифри версії",
      blender.download_page("5.1/../../x") ==
      "https://download.blender.org/release/Blender5.1/")

print()
print("=" * 64)
print("2. Потрібна версія: установлена, показана людиною, відсутня")
print("=" * 64)
b42 = fake_exe("Blender 4.2", "blender.exe")
b51 = fake_exe("portable", "blender-5.1.0-windows-x64", "blender.exe")
real_installed = blender.installed
blender.installed = lambda fresh=False: {"4.2": b42}
check("установлена знаходиться (5.1.9 = 5.1 теж так)", blender.find("4.2.9") == b42)
check("відсутня — None", blender.find("5.1") is None)
check("показана людиною — береться", blender.find("5.1", {"5.1": b51}) == b51)
check("показана, але її вже немає на диску — не береться",
      blender.find("5.1", {"5.1": os.path.join(base, "gone.exe")}) is None)
check("найновіша серед усіх", blender.newest({"5.1": b51}) == b51)
check("жодної — None", (setattr(blender, "installed", lambda fresh=False: {}),
                         blender.newest())[1] is None)
blender.installed = real_installed

print()
print("=" * 64)
print("3. Запуск: окремий процес, launcher без чорного вікна")
print("=" * 64)
calls = []


class FakePopen:
    def __init__(self, args, **kw):
        calls.append((args, kw))


real_popen = subprocess.Popen
subprocess.Popen = FakePopen
try:
    scene = fake_exe("проєкт", "сцена.blend")
    blender.launch(b42, scene)
    args, kw = calls[-1]
    if desktop.WINDOWS:
        check("без launcher поруч — сам blender.exe", args == [b42, scene], args)
        launcher = fake_exe("Blender 4.2", "blender-launcher.exe")
        blender.launch(b42, scene)
        check("launcher поруч — через нього (так відкриває й Windows)",
              calls[-1][0] == [launcher, scene], calls[-1][0])
        flags = calls[-1][1].get("creationflags", 0)
        check("процес окремий — переживе закриття APSVN", flags & 0x8 and flags & 0x200,
              hex(flags))
    check("тека сцени — робоча (відносні шляхи в Blender)",
          kw.get("cwd") == os.path.dirname(scene), kw.get("cwd"))
finally:
    subprocess.Popen = real_popen

print()
print("=" * 64)
print("4. Ця машина (лише звірка з диском)")
print("=" * 64)
found = blender.installed(fresh=True)
print("  знайдено:", ", ".join(sorted(found, key=blender.vkey)) or "нічого")
check("усе знайдене справді лежить на диску",
      all(os.path.exists(p) for p in found.values()), found)
check("ключі — лише major.minor",
      all(blender.parse_version(v) == v for v in found), list(found))
if desktop.WINDOWS:
    check("нічийого розширення система не відкриває",
          desktop.default_app(".zzz-apsvn-test") is None)
    check("а .txt — відкриває", bool(desktop.default_app(".txt")),
          desktop.default_app(".txt"))
else:
    check("поза Windows — «не знаємо», вирішує система",
          desktop.default_app(".blend") is None)

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
