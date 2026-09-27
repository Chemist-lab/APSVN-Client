# -*- coding: utf-8 -*-
"""Який Blender відкриває .blend — версія студії, а не випадковість.

Раніше APSVN віддавав файл системі (os.startfile), і відкривався той Blender,
який Windows вважає «за замовчуванням» для .blend. У кожного художника він
свій: на машині адміністратора 2026-09-27 це був 5.1 (колись вибрали у
«Відкрити за допомогою»), інсталятор записав 4.2, а стоять ще 4.0–5.2. Сцена,
збережена в одній версії, в іншій може щось загубити, тож студія задає ОДНУ
версію на сервері (див. app.server_status), а APSVN на кожній машині
знаходить саме її.

Де шукаємо на Windows — лише читаючи реєстр і диск, нічого не запускаючи:
  * теки інсталятора: Program Files\\Blender Foundation\\Blender <версія>;
  * ProgId, які інсталятор реєструє для .blend: blender.<версія> ->
    shell\\open\\command (так знаходиться й Blender, поставлений деінде);
  * «Програми та компоненти» (Uninstall): DisplayVersion + InstallLocation.
Портативний Blender (розпакований zip) людина показує сама — тоді версію
питаємо в самого blender.exe (--version): назві теки не віримо.
macOS: /Applications і ~/Applications, Blender*.app, версія з Info.plist.
"""
import os
import re
import subprocess
import sys
import time

import desktop

_VER = re.compile(r"(\d+)\.(\d+)")
_CACHE = {"at": 0.0, "found": None}
CACHE_TTL = 30          # с: реєстр і теки не змінюються від кліку до кліку


def parse_version(text):
    """"5.1", "5.1.2", "Blender 4.2 LTS", "blender.5.1" -> "5.1"; інакше None.

    Студія живе версіями major.minor: так звуться теки інсталятора, і нова
    латка (5.1.2) ставиться поверх попередньої, а не поруч.
    """
    m = _VER.search(str(text or ""))
    return "%d.%d" % (int(m.group(1)), int(m.group(2))) if m else None


def vkey(v):
    """Для сортування: 4.10 новіша за 4.9."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def _exe_in(folder):
    for name in ("blender.exe", "blender-launcher.exe"):
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            return full
    return None


def _win_installed():
    import winreg

    found = {}

    def add(ver, exe):
        v = parse_version(ver)
        if v and exe and os.path.isfile(exe) and v not in found:
            found[v] = exe

    # 1. Теки інсталятора
    bases = {os.environ.get(k) for k in ("ProgramW6432", "ProgramFiles",
                                          "ProgramFiles(x86)")}
    if os.environ.get("LOCALAPPDATA"):
        bases.add(os.path.join(os.environ["LOCALAPPDATA"], "Programs"))
    for base in filter(None, bases):
        root = os.path.join(base, "Blender Foundation")
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            if name.lower().startswith("blender"):
                add(name, _exe_in(os.path.join(root, name)))

    def read(hive, sub, value=""):
        try:
            with winreg.OpenKey(hive, sub) as k:
                return winreg.QueryValueEx(k, value)[0]
        except OSError:
            return None

    # 2. ProgId, зареєстровані для .blend
    progids = set()
    for hive, sub in ((winreg.HKEY_CLASSES_ROOT, r".blend\OpenWithProgids"),
                      (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows"
                       r"\CurrentVersion\Explorer\FileExts\.blend\OpenWithProgids")):
        try:
            with winreg.OpenKey(hive, sub) as k:
                i = 0
                while True:
                    try:
                        progids.add(winreg.EnumValue(k, i)[0])
                    except OSError:
                        break
                    i += 1
        except OSError:
            pass
    default = read(winreg.HKEY_CLASSES_ROOT, ".blend")
    if default:
        progids.add(default)
    for pid in progids:
        if not str(pid).lower().startswith("blender"):
            continue
        cmd = read(winreg.HKEY_CLASSES_ROOT, pid + r"\shell\open\command") or ""
        m = re.match(r'\s*"([^"]+)"|\s*(\S+)', cmd)
        exe = (m.group(1) or m.group(2)) if m else None
        if exe:
            folder = os.path.dirname(exe)
            add(parse_version(pid) or os.path.basename(folder),
                _exe_in(folder) or exe)

    # 3. «Програми та компоненти»
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                root = winreg.OpenKey(hive, sub)
            except OSError:
                continue
            with root:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    shown = read(hive, sub + "\\" + name, "DisplayName") or ""
                    if "blender" not in str(shown).lower():
                        continue
                    where = read(hive, sub + "\\" + name, "InstallLocation")
                    ver = read(hive, sub + "\\" + name, "DisplayVersion") or shown
                    if where:
                        add(ver, _exe_in(where))
    return found


def _mac_installed():
    import plistlib

    found = {}
    for root in ("/Applications", os.path.expanduser("~/Applications")):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            if not (name.lower().startswith("blender") and name.endswith(".app")):
                continue
            app = os.path.join(root, name)
            try:
                with open(os.path.join(app, "Contents", "Info.plist"), "rb") as fh:
                    info = plistlib.load(fh)
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            v = parse_version(info.get("CFBundleShortVersionString"))
            if v and v not in found:
                found[v] = app
    return found


def installed(fresh=False):
    """{"5.1": шлях, …} — які Blender'и стоять на цій машині."""
    if not fresh and _CACHE["found"] is not None and \
            time.time() - _CACHE["at"] < CACHE_TTL:
        return dict(_CACHE["found"])
    try:
        found = (_win_installed() if desktop.WINDOWS
                 else _mac_installed() if desktop.MAC else {})
    except Exception:
        found = {}              # пошук Blender'а ніколи не має валити відкриття
    _CACHE.update(at=time.time(), found=found)
    return dict(found)


def everything(custom=None):
    """Установлені плюс показані людиною (портативні) — останні важливіші."""
    out = installed()
    for v, exe in (custom or {}).items():
        if parse_version(v) and exe and os.path.exists(exe):
            out[parse_version(v)] = exe
    return out


def find(version, custom=None):
    """Шлях до Blender'а потрібної версії на цій машині, або None."""
    v = parse_version(version)
    return everything(custom).get(v) if v else None


def newest(custom=None):
    got = everything(custom)
    return got[max(got, key=vkey)] if got else None


def version_from_output(text):
    """«Blender 5.1.0\\n\\tbuild date: …» -> "5.1"."""
    m = re.search(r"Blender\s+(\d+\.\d+)", str(text or ""))
    return parse_version(m.group(1)) if m else None


def probe(exe):
    """Яка це версія — питаємо сам Blender (--version виходить одразу).

    Для портативного Blender'а, якого людина показала сама. blender-launcher
    — програма без консолі й нічого не друкує, тож питаємо blender.exe поруч.
    """
    target = exe
    if desktop.MAC and exe.endswith(".app"):
        target = os.path.join(exe, "Contents", "MacOS", "Blender")
    elif os.path.basename(exe).lower() == "blender-launcher.exe":
        target = os.path.join(os.path.dirname(exe), "blender.exe")
    try:
        r = subprocess.run([target, "--version"], capture_output=True, timeout=60,
                           **desktop.no_window())
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    return version_from_output(out)


def launch(exe, path):
    """Відкрити файл саме в цьому Blender'і — окремим процесом, що переживе нас.

    На Windows — blender-launcher.exe, якщо він поруч (так робить і сама
    система): голий blender.exe — консольна програма й відкрив би ще чорне
    вікно. На маку — open -a з конкретним .app.
    """
    if desktop.MAC:
        subprocess.Popen(["open", "-a", exe, path])
        return True
    run = exe
    if desktop.WINDOWS:
        side = os.path.join(os.path.dirname(exe), "blender-launcher.exe")
        if os.path.isfile(side):
            run = side
    kw = {}
    if desktop.WINDOWS:
        kw["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8) |
                               getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    else:
        kw["start_new_session"] = True
    subprocess.Popen([run, path], cwd=os.path.dirname(path) or None,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, **kw)
    return True


def download_page(version):
    """Сторінка завантаження саме цієї версії на blender.org (або загальна)."""
    v = parse_version(version)
    return ("https://download.blender.org/release/Blender%s/" % v if v
            else "https://www.blender.org/download/")


if __name__ == "__main__":         # python blender.py — що знайдено тут
    for v, exe in sorted(installed(fresh=True).items(), key=lambda x: vkey(x[0])):
        print(v, exe)
    sys.exit(0)
