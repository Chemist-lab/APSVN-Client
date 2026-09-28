# -*- coding: utf-8 -*-
"""Прибирання старих копій файлів (.svn/pristine) — само, у фоні, безпечно.

Задача від серверної сесії (2026-09-28): svn тримає оригінал кожної версії
файлу, яку мала копія, і на проєкті 56 ГіБ за п'ять робочих днів копія
виросла на 45 ГіБ. Тут — на тимчасовому file://-репозиторії:
  * кілька здач великого файлу -> .svn/pristine росте;
  * `cleanup --vacuum-pristines` повертає його до розміру самих файлів;
  * зайнята копія (блокування в wc.db) — тиха відмова, блокування ціле;
  * автоматично — ніколи не голий `cleanup` (той знімає чужі блокування);
  * після здачі й оновлення, при старті й раз на добу — само, у фоні.
"""
import getpass
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import svn_client as sc
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


ME = getpass.getuser()
base = tempfile.mkdtemp(prefix="apsvn_tidy_")
app.CONF_DIR = os.path.join(base, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.LOG = os.path.join(app.CONF_DIR, "error.log")
app.ACTIVITY = os.path.join(app.CONF_DIR, "apsvn.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")
os.makedirs(app.CONF_DIR, exist_ok=True)


class FakeKeyring:
    def __init__(self): self.d = {}
    def set_password(self, s, u, p): self.d[(s, u)] = p
    def get_password(self, s, u): return self.d.get((s, u))


app.keyring = FakeKeyring()
app.Api.TIDY_DELAY = 0

repo = os.path.join(base, "repo")
wc = os.path.join(base, "Проєкт")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace("\\", "/").lstrip("/")
api = app.Api()
api.add_project(url, wc, ME, "pw", name="Проєкт")
pid = api.c["id"]
MB = 1024 * 1024
BIG = "сцена.blend"


def write_big(seed):
    full = os.path.join(wc, BIG)
    if os.path.exists(full):
        os.chmod(full, 0o666)
    with open(full, "wb") as fh:
        fh.write(os.urandom(3 * MB))


def wait_tidy(timeout=30):
    end = time.time() + timeout
    while pid in api._tidying and time.time() < end:
        time.sleep(0.05)


print("=" * 64)
print("1. Здачі великого файлу -> .svn/pristine росте; vacuum повертає")
print("=" * 64)
write_big(0)
sc.add(wc, [BIG])
sc.commit(wc, [BIG], "перша версія")
for i in range(1, 4):
    write_big(i)
    sc.commit(wc, [BIG], "версія %d" % i)
grown = sc.pristine_size(wc)
check("після 4 здач 3-мегабайтного файлу — чотири його копії", grown >= 11 * MB,
      app.human_size(grown))
got = sc.vacuum(wc)
check("vacuum: було -> стало", got and got[0] == grown and got[1] < 4 * MB,
      got and (app.human_size(got[0]), app.human_size(got[1])))
st = sc.status(wc)
check("…а сам файл і копія цілі (змін немає)", not any(f["path"] == BIG for f in st), st)
with open(os.path.join(wc, BIG), "rb") as fh:
    check("…і файл читається повністю", len(fh.read()) == 3 * MB)

print()
print("=" * 64)
print("2. Зайнята копія: тиха відмова, блокування — ціле")
print("=" * 64)
db = os.path.join(wc, ".svn", "wc.db")
con = sqlite3.connect(db)
con.execute("INSERT INTO WC_LOCK (wc_id, local_dir_relpath, locked_levels) VALUES (1, '', -1)")
con.commit()
con.close()
got = sc.vacuum(wc)
check("копію тримає «інша програма» — vacuum відмовляє, нічого не ламаючи", got is None, got)
con = sqlite3.connect(db)
left = con.execute("SELECT COUNT(*) FROM WC_LOCK").fetchone()[0]
con.close()
check("…і чуже блокування лишилося на місці (голий cleanup зняв би його)", left == 1, left)
calls = []
real_run = sc._run


def spy(args, **kw):
    calls.append((list(args), kw.get("_retry", True)))
    return real_run(args, **kw)


sc._run = spy
try:
    got = api._tidy(api.c)
finally:
    sc._run = real_run
check("автоматичне прибирання теж просто пропускає зайняту копію", got is None, got)
check("…і ні разу не запускає голий cleanup — лише --vacuum-pristines, без повтору",
      calls and all(a[:2] == ["cleanup", "--vacuum-pristines"] and r is False
                    for a, r in calls if a and a[0] == "cleanup"), calls)
with open(app.ACTIVITY, encoding="utf-8") as fh:
    check("у журналі — що пропущено й чому", "busy" in fh.read())
con = sqlite3.connect(db)
con.execute("DELETE FROM WC_LOCK")
con.commit()
con.close()

print()
print("=" * 64)
print("3. Само: після здачі, після оновлення, при старті й раз на добу")
print("=" * 64)
for i in range(3):
    api.do_lock([BIG])                 # бінарник APSVN здає лише зайнятим
    write_big(20 + i)
    api.do_commit([BIG], "здача %d" % i)
    wait_tidy()
after = sc.pristine_size(wc)
check("після кожної здачі прибрано — копія не росте", after < 4 * MB,
      app.human_size(after))
t = api._tidied.get(pid) or {}
check("останнє прибирання пам'ятається: скільки звільнено", t.get("freed", 0) >= 2 * MB, t)
with open(app.ACTIVITY, encoding="utf-8") as fh:
    log = fh.read()
check("і записане в журнал: було -> стало, звільнено", ".svn/pristine" in log and "freed" in log,
      log[-200:])
s = api.state()
check("стан для інтерфейсу несе останнє прибирання (для підказки)",
      (s.get("tidy") or {}).get("at") == t.get("at"), s.get("tidy"))

seen = []
real_soon = api._tidy_soon
api._tidy_soon = lambda pid=None, wait=False: seen.append("soon")
try:
    api.do_update()
finally:
    api._tidy_soon = real_soon
check("після оновлення — теж", seen == ["soon"], seen)

write_big(40)
sc.commit(wc, [BIG], "здано повз APSVN — копія знову виросла")
api.c["tidied_at"] = time.time() - 25 * 3600
api.state()
wait_tidy()
check("давно не прибирали — прибирається само (при старті й раз на добу)",
      sc.pristine_size(wc) < 4 * MB and time.time() - api.c["tidied_at"] < 60)
before = sc.pristine_size(wc)
write_big(41)
sc.commit(wc, [BIG], "і ще")
api.state()
wait_tidy()
check("щойно прибирали — від опитування не прибирається знову (лише від дій)",
      sc.pristine_size(wc) > before)

print()
print("=" * 64)
print("4. Іде передача — не пхаємося")
print("=" * 64)
grown = sc.pristine_size(wc)
api.busy.set()
try:
    got = api._tidy(api.c)
finally:
    api.busy.clear()
check("прибирання посеред передачі пропускається", got is None and
      sc.pristine_size(wc) == grown)
api._tidy_soon(wait=True)
check("а щойно вільно — прибирає", sc.pristine_size(wc) < grown)

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
