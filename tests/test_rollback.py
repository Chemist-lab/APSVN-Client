# -*- coding: utf-8 -*-
"""Історію на сервері відкотили — копія з новішими ревізіями лікується.

Справжній випадок 2026-10-03: вісім тестових здач (r29-r36) прибрали з
сервера, і копія художника, де .blend стояв на r36, на кожному оновленні
падала з «E160006: No such reported revision '36'». Тут те саме на
тимчасовому file://-сховищі: «відкіт» — dump до r2 і заміна сховища (UUID
той самий, адреса та сама). Перевіряємо:
  * помилка розпізнається як відкіт, а не сирий E160006;
  * план: що новіше за сервер, скільки качати, чи досить точкового лікування;
  * точкове лікування: жоден байт на диску не змінився, зміни — змінами,
    нове — новим, оновлення й здача знову працюють, лок повернуто;
  * стертий руками файл; уся копія новіша за сервер (була «Get latest»);
    незавершена дія svn на таких вузлах — тоді копія перекачується цілком;
  * переривання посередині: вміст на місці, наступне «Repair» довершує;
  * у програмі: смуга замість сирої помилки, лікування, журнал.
"""
import getpass
import hashlib
import os
import shutil
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
base = tempfile.mkdtemp(prefix="apsvn_rollback_")
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
app.Api.TIDY_EVERY = float("inf")


def url_of(repo):
    return "file:///" + repo.replace("\\", "/").lstrip("/")


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.chmod(path, 0o666)
    with open(path, "wb") as fh:
        fh.write(data)


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


SCENE = "Assets/Сцена.blend"              # кирилиця — як у справжніх проєктах


def make(name):
    """Сховище r1..r4 і копія на ньому. r3 додає нові файли й теку."""
    repo = os.path.join(base, name + "-repo")
    wc = os.path.join(base, name)
    subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
    sc.checkout(url_of(repo), wc)
    W = lambda r: os.path.join(wc, r.replace("/", os.sep))
    put(W(SCENE), b"v1\n" * 4000)
    put(W("Assets/tex.png"), b"texture")
    sc.add(wc, ["Assets"])
    sc.commit(wc, ["Assets"], "r1")
    put(W(SCENE), b"v2\n" * 5000)
    sc.commit(wc, [SCENE], "r2")
    put(W(SCENE), b"v3\n" * 6000)
    put(W("Assets/new.blend"), b"new file\n")
    put(W("Assets/Shots/sh010.blend"), b"shot\n")
    sc.add(wc, ["Assets/new.blend", "Assets/Shots"])
    sc.commit(wc, [SCENE, "Assets/new.blend", "Assets/Shots"], "r3")
    put(W(SCENE), b"v4\n" * 7000)
    sc.commit(wc, [SCENE], "r4")
    return repo, wc, W


def roll_back(repo, to):
    """Відкіт сервера: dump до ревізії `to`, нове сховище замість старого."""
    dump = subprocess.run([sc.SVNADMIN, "dump", "-q", "-r", "0:%d" % to, repo],
                          capture_output=True, check=True).stdout

    def writable(fn, path, _exc):           # FSFS робить ревізії read-only
        os.chmod(path, 0o666)
        fn(path)

    shutil.rmtree(repo, onexc=writable)
    subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
    subprocess.run([sc.SVNADMIN, "load", "-q", repo], input=dump, check=True,
                   capture_output=True)


def rescue_left(wc):
    parent = os.path.dirname(wc)
    return [n for n in os.listdir(parent) if n.startswith(".apsvn-rescue-")]


def stat_of(wc):
    """Статус очима APSVN: шлях -> стан (кирилиця ціла, на відміну від тексту svn)."""
    return {f["path"]: f["status"] for f in sc.status(wc)}


print("=" * 64)
print("1. Відкіт розпізнається, а не сирий E160006")
print("=" * 64)
repo, wc, W = make("a")
put(W(SCENE), b"v5 - work after the last submit\n" * 3000)   # робота після r4
mine = digest(W(SCENE))
sc.lock(wc, [SCENE])
roll_back(repo, 2)
try:
    sc.update(wc)
    check("оновлення падає", False)
except sc.RolledBackError as e:
    check("оновлення — RolledBackError (і це SvnError)", isinstance(e, sc.SvnError))
    check("текст людський і каже, що робити",
          "rolled back" in str(e) and "Repair" in str(e) and "E160006" not in str(e),
          str(e))
try:
    sc.status(wc, remote=True)
    check("звірка з сервером падає", False)
except sc.RolledBackError:
    check("звірка з сервером — теж RolledBackError", True)

print()
print("=" * 64)
print("2. План: що новіше за сервер і як лікувати")
print("=" * 64)
plan = sc.rollback_plan(wc)
check("сервер — r2, копія — r4", plan["head"] == 2 and plan["newest"] == 4, plan)
check("лише найвищі вузли, новіші за сервер",
      plan["nodes"] == ["Assets/Shots", "Assets/new.blend", SCENE], plan["nodes"])
check("корінь цілий — точково, без перекачування", plan["full"] is False)
check("лок на сцені помічено, щоб повернути", plan["locks"] == [SCENE], plan["locks"])
check("качати — лише сцену в її версії r2 (нового на сервері немає)",
      plan["bytes"] == len(b"v2\n" * 5000) and plan["on_server"] == 1,
      (plan["bytes"], plan["on_server"]))

print()
print("=" * 64)
print("3. Точкове лікування: на диску не змінився жоден байт")
print("=" * 64)
tex = digest(W("Assets/tex.png"))
res = sc.repair_rollback(wc, me=ME)
check("вміст сцени — твій, байт у байт", digest(W(SCENE)) == mine)
check("нові файли з відкочених здач лишились",
      open(W("Assets/new.blend"), "rb").read() == b"new file\n" and
      open(W("Assets/Shots/sh010.blend"), "rb").read() == b"shot\n")
check("незачеплене — незачеплене", digest(W("Assets/tex.png")) == tex)
st = stat_of(wc)
check("сцена — зміна, нове — нове, і більше нічого (здати знову чи скасувати)",
      st == {SCENE: "modified", "Assets/new.blend": "unversioned",
             "Assets/Shots": "unversioned"}, st)
check("підсумок: збережено 3 файли, нічого не лишилось у порятунку",
      res["kept"] == 3 and res["left"] == [], res)
check("тека порятунку прибрана", rescue_left(wc) == [], rescue_left(wc))
check("лок повернуто — сцену можна писати далі",
      sc.holds_lock(wc, SCENE) and res["lost_locks"] == [], res["lost_locks"])
try:
    sc.update(wc)
    check("оновлення знову працює", True)
except sc.SvnError as e:
    check("оновлення знову працює", False, e.raw)
out = sc.commit(wc, [SCENE], "знову v5")
check("і здача: та сама робота стає r3", "commit 3" in out, out)
check("план після лікування порожній",
      not sc.rollback_plan(wc)["nodes"] and not sc.rollback_pending(wc))

print()
print("=" * 64)
print("4. Файл, стертий руками, і уся копія новіша за сервер")
print("=" * 64)
repo, wc, W = make("b")
os.remove(W(SCENE))
roll_back(repo, 2)
sc.repair_rollback(wc, me=ME)
check("стертий файл повернувся версією сервера, без зміни",
      open(W(SCENE), "rb").read() == b"v2\n" * 5000 and
      SCENE not in stat_of(wc), stat_of(wc))

repo, wc, W = make("c")
subprocess.run([sc.SVN, "update", "--non-interactive"], cwd=wc, capture_output=True)
put(W("Assets/tex.png"), b"texture, repainted")
before = {r: digest(W(r)) for r in (SCENE, "Assets/tex.png", "Assets/new.blend",
                                    "Assets/Shots/sh010.blend")}
roll_back(repo, 2)
plan = sc.rollback_plan(wc)
check("після «Get latest» новіший за сервер сам корінь — перекачувати цілком",
      plan["full"] is True and plan["nodes"] == [], plan)
sc.repair_rollback(wc, me=ME)
check("файли на диску ті самі, байт у байт",
      all(digest(W(r)) == h for r, h in before.items()))
st = stat_of(wc)
check("що відрізняється — зміна, чого на сервері немає — нове",
      st == {SCENE: "modified", "Assets/tex.png": "modified",
             "Assets/new.blend": "unversioned", "Assets/Shots": "unversioned"}, st)
try:
    sc.update(wc)
    check("оновлення знову працює", True)
except sc.SvnError as e:
    check("оновлення знову працює", False, e.raw)
check("стара .svn не лишилась ні в проєкті, ні поруч",
      not [n for n in os.listdir(wc) if n.startswith(".svn") and n != ".svn"]
      and rescue_left(wc) == [], (os.listdir(wc), rescue_left(wc)))

repo, wc, W = make("d")
put(W("Assets/Shots/sh020.blend"), b"waiting to be added\n")
sc.add(wc, ["Assets/Shots/sh020.blend"])
roll_back(repo, 2)
plan = sc.rollback_plan(wc)
check("незавершена дія svn на таких вузлах — теж цілком (частинами не лікується)",
      plan["full"] is True, plan)
sc.repair_rollback(wc, me=ME)
check("…і той файл лежить, де лежав",
      open(W("Assets/Shots/sh020.blend"), "rb").read() == b"waiting to be added\n")

print()
print("=" * 64)
print("5. Перервали посередині: вміст на місці, наступне «Repair» довершує")
print("=" * 64)
repo, wc, W = make("e")
put(W(SCENE), b"precious work\n" * 3000)
precious = digest(W(SCENE))
roll_back(repo, 2)
real_run = sc._run


def flaky(args, **kw):
    if args[:3] == ["update", "--set-depth", "infinity"]:
        raise sc.SvnError("No connection to the server.", "svn: E170013: Unable to connect")
    return real_run(args, **kw)


sc._run = flaky
try:
    sc.repair_rollback(wc, me=ME)
    check("обрив посеред лікування видно", False)
except sc.SvnError:
    check("обрив посеред лікування видно", True)
finally:
    sc._run = real_run
check("вміст сцени — на місці, байт у байт", digest(W(SCENE)) == precious)
check("копія пам'ятає, що лікування не скінчено", sc.rollback_pending(wc))
check("тека порятунку не лишилась (вміст повернуто)", rescue_left(wc) == [])
plan = sc.rollback_plan(wc)
check("наступний план довершує ті самі вузли",
      set(plan["nodes"]) == {"Assets/Shots", "Assets/new.blend", SCENE}, plan)
sc.repair_rollback(wc, me=ME)
check("довершено: сцена — зміна з твоїм вмістом",
      digest(W(SCENE)) == precious and stat_of(wc).get(SCENE) == "modified",
      stat_of(wc))
check("позначку незавершеного прибрано", not sc.rollback_pending(wc))
try:
    sc.update(wc)
    check("оновлення працює", True)
except sc.SvnError as e:
    check("оновлення працює", False, e.raw)

print()
print("=" * 64)
print("6. У програмі: смуга, лікування, журнал")
print("=" * 64)
repo = os.path.join(base, "f-repo")
wc = os.path.join(base, "Проєкт")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
api = app.Api()
api.add_project(url_of(repo), wc, ME, "pw", name="Проєкт")
W = lambda r: os.path.join(wc, r.replace("/", os.sep))
put(W("scene.txt"), b"one\n")
sc.add(wc, ["scene.txt"])
api.do_commit(["scene.txt"], "r1")
put(W("scene.txt"), b"two\n")
api.do_commit(["scene.txt"], "r2")
put(W("scene.txt"), b"three\n")
api.do_commit(["scene.txt"], "r3")
roll_back(repo, 1)
s = api.state(remote=True)
check("смуга замість сирої помилки", s.get("rolled_back") is True and not s.get("warn"),
      (s.get("rolled_back"), s.get("warn")))
plan = api.rollback_plan()
check("план для вікна згоди", plan["head"] == 1 and plan["newest"] == 3 and
      plan["nodes"] == ["scene.txt"], plan)
out = api.do_repair_rollback()
check("відповідь: що лишилось як було і що далі",
      out.startswith("Repaired. 1 file stayed exactly as it was") and
      "commit 1 is in Changes" in out and "submit it again or discard it" in out, out)
with open(app.ACTIVITY, encoding="utf-8") as fh:
    log = fh.read()
check("у журналі — що й де лікували",
      "repair after rollback Проєкт: server at r1, copy had r3" in log and
      "fixed scene.txt" in log, log.strip().splitlines()[-1:])
# після лікування у фоні прибираються старі копії файлів — дочекатись
end = time.time() + 30
while api._tidying and time.time() < end:
    time.sleep(0.05)
s = api.state(remote=True)
check("після лікування смуги немає", not s.get("rolled_back") and not s.get("warn"), s.get("warn"))
check("вміст — твій (three), і він — зміна",
      open(W("scene.txt"), "rb").read() == b"three\n" and
      any(f["path"] == "scene.txt" and f["status"] == "modified"
          for f in s.get("files") or []), s.get("files"))
check("повторне лікування — чесне «нема чого»",
      "nothing to repair" in api.do_repair_rollback())

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
