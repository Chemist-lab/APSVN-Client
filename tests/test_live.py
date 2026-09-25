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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "app"))
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

# --- сервер студії: прев'ю, залежності, задачі — ТІЛЬКИ ЧИТАННЯ --------------
# Статуси й коментарі тут не чіпаються: це дані людей, і перевірка не має
# права лишати в стрічці чужої задачі слід. Запис перевіряє test_server.py
# на підробному сервері.
import json

print()
if not a._where():
    print("ПРОПУЩЕНО (сервер студії): адреса проєкту не svn-native —", url)
else:
    s = a.server_status(force=True)
    check("сервер студії пускає тим самим логіном", s.get("ok") is True, s)
    check("сервер уміє задачі (образ перезібрано)", s.get("tasks") is True, s)
    ov = a.tasks_overview(force=True)
    check("задачі проєкту читаються", ov.get("ok") is True,
          ov.get("error") or "%d задач (разом із завершеними)" % len(ov.get("tasks") or []))
    # Шоти й процеси — лише коли сервер їх оголошує. Він їх і прибирав: облік
    # задач переїхав у Kitsu, і /processes та /shots зникли. Клієнт тоді
    # просто не показує смуги шоту — перевіряємо, що не падає.
    cl, _pre = a._client()
    if s.get("shots"):
        try:
            procs = cl.processes().get("processes") or []
            check("процеси читаються — з кроками по черзі",
                  all(isinstance(p.get("steps"), list) for p in procs),
                  ["%s: %s" % (p.get("name"), " → ".join(x.get("name") for x in p["steps"]))
                   for p in procs])
        except Exception as e:
            check("процеси читаються — з кроками по черзі", False, e)
        try:
            shots = cl.shots().get("shots")
            check("шоти проєкту читаються", isinstance(shots, list), "%d шотів" % len(shots))
        except Exception as e:
            check("шоти проєкту читаються", False, e)
    else:
        first = (ov.get("tasks") or [{}])[0]
        check("сервер без шотів: смуга шоту просто не показується, без винятку",
              a.shot_pipeline(first.get("entity") or 1) is None)
    try:
        done = a.tasks_done()
        check("завершені задачі читаються", isinstance(done, list), len(done))
    except sc.SvnError as e:
        check("завершені задачі читаються", False, e)

    # перший .blend у копії, не глибше двох тек
    blend = None
    for root_dir, dirs, names in os.walk(wc):
        dirs[:] = [d for d in dirs if d != ".svn"]
        if root_dir.count(os.sep) - wc.count(os.sep) >= 2:
            dirs[:] = []
        hit = [n for n in names if n.lower().endswith(".blend")]
        if hit:
            blend = os.path.relpath(os.path.join(root_dir, hit[0]),
                                    wc).replace("\\", "/")
            break
    if not blend:
        print("  (у копії немає .blend — прев'ю й залежності не перевірено)")
    else:
        print("  .blend для перевірки:", blend)
        uri = a.previews([{"path": blend, "rev": None}]).get(blend + "@") or ""
        check("прев'ю .blend з сервера — картинка", uri.startswith("data:image/"),
              uri[:30])
        t0 = time.time()
        a.previews([{"path": blend, "rev": None}])
        check("друге прев'ю — з пам'яті", time.time() - t0 < 0.05,
              "%.3f с" % (time.time() - t0))
        v = a.file_versions(blend)
        check("версії файлу з картинками", bool(v.get("ok") and v.get("versions")),
              v.get("error") or "%d версій" % len(v.get("versions") or {}))
        revs = [r["rev"] for r in sc.file_log(wc, blend, username=u, password=p)[:5]]
        check("ревізії версій — ті самі, що в історії svn",
              set(revs) <= set(v.get("versions") or {}),
              (revs, sorted(v.get("versions") or {})))
        mine_row = {f["path"]: f for f in sc.status(wc, me=u)}.get(blend, {})
        if mine_row.get("status") in (None, "normal"):
            t0 = time.time()
            wv = a.which_version(blend)
            check("незмінений файл упізнано серед версій за SHA-1",
                  bool(wv and wv.get("rev")), "%s, %.1f с" % (wv, time.time() - t0))
        fl = a.file_links(blend)
        dp = fl.get("deps") or {}
        check("залежності сцени читаються", dp.get("state") in ("ok", "pending"),
              dp.get("note") or dp.get("state"))
        size = len(json.dumps(fl))
        check("залежності зведено, а не передано поіменно", size < 20000,
              "%d байт через міст до інтерфейсу" % size)

print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
