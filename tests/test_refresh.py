# -*- coding: utf-8 -*-
"""«Get latest» має спрацювати завжди — і після нього оновитися все.

Звідки взялося «не завжди оновлюється». Кожні 10 с інтерфейс звіряється з
сервером: state() тримає замок дій, поки йде `svn status -u` по мережі. А
_guard, через який ідуть УСІ дії, замок не чекав — одразу відмовляв: «Please
wait — the previous action is still running». Тобто «Get latest», натиснутий
саме тоді, коли йшла фонова звірка, не робив нічого, крім тосту, — і людина
бачила старий стан. Те саме з локом, здачею, будь-якою дією.

Тут це відтворено без удачі: фонова звірка штучно триває секунду, і дія
приходить посеред неї.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "app"))
import svn_client as sc
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_refresh_")
app.CONF_DIR = os.path.join(base, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.LOG = os.path.join(app.CONF_DIR, "error.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")


class FakeKeyring:
    def __init__(self):
        self.d = {}

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def get_password(self, s, u):
        return self.d.get((s, u))


app.keyring = FakeKeyring()
repo = os.path.join(base, "repo")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace(os.sep, "/").lstrip("/")
wc = os.path.join(base, "wc")
api = app.Api()
api.add_project(url, wc, "anya", "pw", name="Оновлення")
with open(os.path.join(wc, "a.txt"), "w") as fh:
    fh.write("one")
api.do_commit(["a.txt"], "перший")

friend = os.path.join(base, "friend")
sc.checkout(url, friend)
with open(os.path.join(friend, "b.txt"), "w") as fh:
    fh.write("from a colleague")
sc.add(friend, ["b.txt"])
sc.commit(friend, ["b.txt"], "колега")

print("=" * 66)
print("1. «Get latest» посеред фонової звірки — чекає її, а не відмовляє")
print("=" * 66)
real_status = sc.status


def slow_status(*a, **kw):
    if kw.get("remote"):
        time.sleep(1.0)            # мережа: звірка з сервером триває секунду
    return real_status(*a, **kw)


sc.status = slow_status
poll = threading.Thread(target=lambda: api.state(remote=True))
poll.start()
time.sleep(0.2)                    # звірка вже йде й тримає замок
t0 = time.time()
try:
    out = api.do_update()
    check("оновлення пройшло, хоч натиснули посеред звірки", "Up to date" in out, out)
except sc.SvnError as e:
    check("оновлення пройшло, хоч натиснули посеред звірки", False, e)
waited = time.time() - t0
poll.join()
sc.status = real_status
check("…дочекавшись її кінця, а не миттєво", waited >= 0.5, "%.2f с" % waited)
check("файл колеги справді приїхав", os.path.isfile(os.path.join(wc, "b.txt")))

print()
print("=" * 66)
print("2. Посеред ДОВГОЇ дії друга не стає в чергу — відмова одразу")
print("=" * 66)
real_cleanup = sc.cleanup


def slow_cleanup(*a, **kw):
    time.sleep(1.5)
    return real_cleanup(*a, **kw)


sc.cleanup = slow_cleanup
long_action = threading.Thread(target=api.do_cleanup)
long_action.start()
time.sleep(0.3)
t0 = time.time()
try:
    api.do_update()
    check("під час довгої дії друга відмовлена", False, "пройшла")
except sc.SvnError as e:
    check("під час довгої дії друга відмовлена", "Please wait" in str(e), e)
check("…одразу, без очікування", time.time() - t0 < 0.5, "%.2f с" % (time.time() - t0))
long_action.join()
sc.cleanup = real_cleanup

print()
print("=" * 66)
print("3. Читання (вміст коміту) не вдає з себе довгу дію")
print("=" * 66)
seen = []
real_rf = sc.revision_files


def spy_rf(*a, **kw):
    seen.append(api.busy.is_set())
    return real_rf(*a, **kw)


sc.revision_files = spy_rf
api.revision_files(1)
sc.revision_files = real_rf
check("поки читається коміт, прапорця «іде передача» немає", seen == [False], seen)

print()
print("=" * 66)
print("4. Після оновлення все, що рахувалося від старої копії, — застаріле")
print("=" * 66)
pid = api.c["id"]
api._tasks[pid] = {"at": time.time(), "out": {"ok": True, "tasks": []}}
api._versions[(pid, "a.txt")] = {"s0": 1}
api._memo[(pid, "shots")] = (time.time(), {"shots": []})
head_before = api._head
api.do_update()
check("задачі спитаються знову", api._tasks[pid]["at"] == 0)
check("версії файлів — теж", not api._versions)
check("шоти — теж", (pid, "shots") not in api._memo)
check("картинки «найновішої версії» беруться наново", api._head == head_before + 1)

print()
print("=" * 66)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 66)
shutil.rmtree(base, ignore_errors=True)
sys.exit(1 if FAIL else 0)
