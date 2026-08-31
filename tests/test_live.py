# -*- coding: utf-8 -*-
"""Перевірка на СПРАВЖНЬОМУ сервері — лише читання, нічого не змінює.

Навіщо окремо від решти: інші набори працюють на тимчасовому file://-репозиторії,
де автентифікації немає взагалі. Через це вони не побачили, що SlikSvn мовчки
ігнорує --password-from-stdin і кожна мережева дія падає. Цей набір бере
збережене підключення (%APPDATA%\\APSVN) і ходить у мережу по-справжньому.

Без збереженого підключення просто пропускається.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "vendor"))

import app
import svn_client as sc

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


a = app.Api()
wc, url = a.c.get("wc"), a.c.get("url")
if not wc or not os.path.isdir(wc) or not url:
    print("ПРОПУЩЕНО: немає збереженого підключення в %APPDATA%\\APSVN")
    sys.exit(0)

print("сервер:", url)
print("копія: ", wc)
print("svn:   ", sc.SVN)
print("пароль зі stdin підтримується:", sc.supports_stdin_password())
print()

u, p = a._creds()
check("логін збережено", bool(u), u)
check("пароль дістається зі сховища Windows", bool(p), "довжина %s" % (len(p) if p else 0))

# --- те, що ламалося: будь-яка дія З ПАРОЛЕМ через мережу ------------------
t0 = time.time()
try:
    files = sc.status(wc, remote=True, username=u, password=p, me=u)
    dt = time.time() - t0
    check("звірка з сервером проходить автентифікацію", True,
          "%.1f с, рядків: %d" % (dt, len(files)))
except sc.SvnError as e:
    check("звірка з сервером проходить автентифікацію", False, e)

try:
    lg = sc.log(wc, limit=5, username=u, password=p)
    check("історія читається з сервера", isinstance(lg, list) and len(lg) > 0, len(lg))
    check("описи не побиті кодуванням", all("?" not in (e["msg"] or "") for e in lg),
          [e["msg"] for e in lg])
except Exception as e:
    check("історія читається з сервера", False, e)

# --- те саме через шар Api, як його смикає інтерфейс -----------------------
s = a.state(remote=True)
check("Api.state() не скаржиться", s.get("configured") is True and not s.get("warn"),
      s.get("warn") or s.get("error"))
check("Api.state() бачить ревізію", (s.get("info") or {}).get("revision") is not None,
      s.get("info"))
check("Api.get_log() повертає історію", len(a.get_log()) > 0)

# --- перевірка самого шляху з паролем, у обхід кешу ------------------------
# На чистому config-dir кешу немає, тож видно, чи пароль справді доходить до
# сервера. Саме тут ловиться зламаний --password-from-stdin.
import shutil
import tempfile

saved = sc._config_dir
sandbox = tempfile.mkdtemp(prefix="apsvn_live_")
try:
    sc.ensure_config(sandbox)
    try:
        sc._run(["info", url], username=u, password=p, timeout=60)
        check("правильний пароль доходить до сервера без кешу", True)
    except sc.SvnError as e:
        check("правильний пароль доходить до сервера без кешу", False, e)

    shutil.rmtree(sandbox, ignore_errors=True)
    sc.ensure_config(sandbox)
    try:
        sc._run(["info", url], username=u, password="definitely-not-it", timeout=60)
        check("хибний пароль відхиляється", False, "сервер пустив — щось не так")
    except sc.SvnError as e:
        check("хибний пароль пояснено правильно", "user name or password" in str(e), e)
finally:
    sc._config_dir = saved
    shutil.rmtree(sandbox, ignore_errors=True)

print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
