# -*- coding: utf-8 -*-
"""Перевірка й встановлення оновлень з GitHub Releases.

ЧОМУ САМЕ РЕЛІЗИ, А НЕ КЛОН РЕПОЗИТОРІЮ. У художника немає git і не буде.
Реліз — це один файл за одним посиланням, який віддає CDN GitHub без жодної
автентифікації, поки репозиторій публічний.

ЧОМУ ПІДМІНА ЙДЕ ОКРЕМИМ ПРОЦЕСОМ. Windows не дає перезаписати файл, який
зараз виконується, а ми замінюємо в тому числі python, яким самі й працюємо.
Тож порядок такий: завантажили -> розклали поруч -> написали сценарій підміни
-> запустили його окремо -> вийшли. Він дочекався, поки нас не стане, і аж
тоді міняє теки. Спроба зробити це «на ходу» дає напівзамінену збірку, яка не
запускається взагалі, — а це вже не оновлення, а знищення програми.

ЩО НІКОЛИ НЕ ЧІПАЄТЬСЯ: налаштування й паролі (вони в теці налаштувань, не в
теці програми) і робоча копія художника (вона взагалі деінде). Оновлення
міняє лише саму програму.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

import desktop

REPO = "Chemist-lab/APSVN-Client"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
PAGE = "https://github.com/%s/releases" % REPO
TIMEOUT = 20

# Файли, за якими впізнаємо, що завантажили саме APSVN, а не щось інше.
# Перевірка дешева, а ціна помилки — розпакувати чуже поверх програми.
MUST_HAVE = ("app.py", "ui/index.html", "svn_client.py")


def parse_version(s):
    """'v1.10.2' -> (1, 10, 2). Порівнюємо числами, а не рядками.

    Інакше '1.10' виявиться меншою за '1.9', і оновлення тихо перестане
    пропонуватись рівно тоді, коли версій стане більше десяти.
    """
    nums = re.findall(r"\d+", str(s or ""))
    return tuple(int(n) for n in nums[:4]) or (0,)


def newer(remote, local):
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _asset_for(assets):
    """Обрати з релізу файл для ЦІЄЇ системи.

    Ім'я збірки для маку закінчується на -mac.zip; віконна — просто .zip.
    Якщо колись з'явиться третя, помилитись тут дешевше, ніж мовчки
    завантажити чужу.
    """
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    mac = [a for a in zips if "-mac" in a["name"].lower()]
    win = [a for a in zips if "-mac" not in a["name"].lower()]
    pick = mac if desktop.MAC else win
    return pick[0] if pick else None


def check(current):
    """Що є на сервері. Ніколи не кидає — мережа не привід валити програму.

    Повертає dict із полями:
      state: ok | none | offline | error
      have / want / notes / url / size / download
    """
    try:
        req = urllib.request.Request(
            API, headers={"Accept": "application/vnd.github+json",
                          "User-Agent": "APSVN"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 404 — релізів ще жодного. Це нормальний стан молодого проєкту, а не
        # поламка, і казати про нього треба спокійно.
        return {"state": "none" if e.code == 404 else "error",
                "have": current, "url": PAGE,
                "detail": "HTTP %s" % e.code}
    except Exception as e:
        return {"state": "offline", "have": current, "url": PAGE,
                "detail": str(e)[:120]}

    tag = data.get("tag_name") or ""
    asset = _asset_for(data.get("assets") or [])
    return {
        "state": "ok",
        "have": current,
        "want": tag.lstrip("vV"),
        "newer": newer(tag, current),
        "notes": (data.get("body") or "").strip()[:4000],
        "url": data.get("html_url") or PAGE,
        "name": asset["name"] if asset else None,
        "size": asset.get("size") if asset else None,
        "download": asset.get("browser_download_url") if asset else None,
    }


def download(url, dest, size=None, progress=None):
    """Завантажити у файл поруч, потім перейменувати.

    Той самий порядок, що й при поверненні старої версії файлу: обрив зв'язку
    не має лишати на диску обрізаний архів, який хтось потім спробує
    розпакувати.
    """
    part = dest + ".part"
    got = 0
    req = urllib.request.Request(url, headers={"User-Agent": "APSVN"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, \
            open(part, "wb") as fh:
        total = size or int(r.headers.get("Content-Length") or 0) or None
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    if size and got != size:
        os.unlink(part)
        raise IOError("downloaded %d bytes, expected %d" % (got, size))
    os.replace(part, dest)
    return dest


def stage(zip_path, into):
    """Розпакувати збірку в порожню теку й переконатися, що це справді APSVN.

    Архів релізу містить теку верхнього рівня (APSVN/…), тож розкладаємо і
    шукаємо всередині корінь із нашими файлами: покладатися на конкретне ім'я
    теки означало б ламатись від першого ж перейменування.
    """
    if os.path.isdir(into):
        shutil.rmtree(into, ignore_errors=True)
    os.makedirs(into, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            # захист від архіву, що намагається писати поза текою
            p = os.path.normpath(os.path.join(into, name))
            if not p.startswith(os.path.normpath(into) + os.sep) \
                    and p != os.path.normpath(into):
                raise IOError("archive tries to write outside: %s" % name)
        if not desktop.MAC:
            z.extractall(into)

    if desktop.MAC:
        # ditto, а не zipfile: на маку збірка — це .app, а він не просто тека.
        # Перевірено на нашому ж архіві, всі три речі одразу: zipfile знімає
        # біт виконуваності (запускач перестає бути запускачем), перетворює
        # символьні посилання всередині Python.framework на копії й ламає
        # підпис — а без підпису на Apple Silicon не стартує взагалі. Тим
        # самим ditto архів і створюється, див. package_mac.sh.
        r = subprocess.run(["ditto", "-x", "-k", zip_path, into],
                           capture_output=True, **desktop.no_window())
        if r.returncode != 0:
            raise IOError("could not unpack the archive: %s"
                          % r.stderr.decode("utf-8", "replace").strip()[:200])

    root = _find_root(into)
    if root is None:
        raise IOError("this does not look like APSVN")
    return root


def _markers(d):
    return all(os.path.exists(os.path.join(d, m.replace("/", os.sep)))
               for m in MUST_HAVE)


def _find_root(top):
    """Тека, у якій лежать наші файли — сама top або один рівень нижче.

    На маку є ще один випадок, і без нього оновлення не працює зовсім: там
    збірка — це APSVN.app, і наших файлів у його корені немає, вони лежать у
    Contents/Resources. Тому коренем вважається сам .app: підмінити треба
    bundle цілком, разом зі своїм Python, svn і підписом.
    """
    cands = [top] + [os.path.join(top, d) for d in _dirs(top)]
    for cand in cands:
        if _markers(cand):
            return cand
    if desktop.MAC:
        for cand in cands:
            if cand.endswith(".app") and \
                    _markers(os.path.join(cand, "Contents", "Resources")):
                return cand
    return None


def _dirs(p):
    try:
        return [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))]
    except OSError:
        return []


def write_swap_script(work, staged, install, pid, relaunch):
    """Сценарій, який дочекається нашої смерті й підмінить теку.

    Лежить у тимчасовій теці, а не в теці програми: інакше він знищив би сам
    себе посеред роботи.

    Стара тека спершу ПЕРЕЙМЕНОВУЄТЬСЯ, а не видаляється. Перейменування
    миттєве й оборотне: якщо підміна не вдалася, повертаємо як було, і
    художник лишається зі старою робочою програмою замість жодної.

    Сам сценарій — СУЦІЛЬНО ASCII, і це не перестрахування. Консольна кодова
    сторінка cp866 покриває російську кирилицю, але не має ані «і», ані «ї»,
    «є», «ґ». Один український коментар у цьому файлі — і оновлення падає на
    останньому кроці, вже після того, як усе завантажено. Пояснення живуть
    тут, у вихідному коді; у тимчасовому сценарії їм робити нічого.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    old = install.rstrip("\\/") + ".old-" + stamp
    if desktop.WINDOWS:
        path = os.path.join(work, "apply.bat")
        body = """@echo off
rem Wait until APSVN is really gone: while the process lives Windows keeps a
rem hold on its files, and any swap would leave a half-replaced build.
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
move "{install}" "{old}" >nul 2>&1
if errorlevel 1 goto giveup
move "{staged}" "{install}" >nul 2>&1
if errorlevel 1 goto restore
start "" "{relaunch}"
rmdir /s /q "{old}" >nul 2>&1
goto done
:restore
move "{old}" "{install}" >nul 2>&1
:giveup
start "" "{relaunch}"
:done
""".format(pid=pid, install=install, old=old, staged=staged,
           relaunch=relaunch)
        # ascii з помилкою, а не з мовчазною заміною: якщо сюди колись
        # залетить не-ASCII, хай це спливе тут, а не в художника
        io.open(path, "w", encoding="ascii", newline="\r\n").write(body)
        return path

    path = os.path.join(work, "apply.sh")
    body = """#!/bin/bash
# Wait until APSVN is really gone before touching anything.
while kill -0 {pid} 2>/dev/null; do sleep 1; done
mv "{install}" "{old}" || {{ open "{relaunch}"; exit 1; }}
mv "{staged}" "{install}" || {{ mv "{old}" "{install}"; open "{relaunch}"; exit 1; }}
open "{relaunch}"
rm -rf "{old}"
""".format(pid=pid, install=install, old=old, staged=staged,
           relaunch=relaunch)
    io.open(path, "w", encoding="utf-8", newline="\n").write(body)
    os.chmod(path, 0o755)
    return path


def launch_detached(script):
    """Запустити сценарій так, щоб він пережив наш вихід.

    Звичайний нащадок помер би разом із нами — а нам треба саме навпаки.
    """
    if desktop.WINDOWS:
        # НЕ DETACHED_PROCESS. Він лишає процес узагалі без консолі, а
        # пакетному файлу вона потрібна: tasklist і ping без неї не
        # працюють, і сценарій просто нічого не робить. Це найгірший
        # різновид помилки: все завантажилось, програма закрилась,
        # і нічого не сталось. CREATE_NO_WINDOW дає консоль, але приховану;
        # нащадка Windows не вбиває разом із батьком, тож він нас переживе.
        FLAGS = 0x08000000 | 0x00000200   # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
        subprocess.Popen(["cmd", "/c", script], creationflags=FLAGS,
                         close_fds=True)
    else:
        subprocess.Popen(["/bin/bash", script], start_new_session=True,
                         close_fds=True)


def work_dir():
    return os.path.join(tempfile.gettempdir(), "apsvn-update")
