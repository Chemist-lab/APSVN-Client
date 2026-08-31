# -*- coding: utf-8 -*-
"""Лічильник «що приїде» — і баг, через який він з'явився.

Скарга була така: людина щойно САМА все здала, а їй пишуть «оновись до
останньої версії». Причина — рахували HEAD мінус ревізія копії. svn піднімає
ревізію лише зданих шляхів, корінь копії лишається на старому числі, тож
різниця майже завжди >= 1 одразу після власної здачі. Тепер рахуємо не
ревізії, а справжні вхідні зміни. Ці перевірки тримають різницю ревізій
похованою.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import svn_client as sc
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_inc_")
app.CONF_DIR = os.path.join(base, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.LOG = os.path.join(app.CONF_DIR, "error.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")


class FakeKeyring:
    def __init__(self): self.d = {}
    def set_password(self, s, u, p): self.d[(s, u)] = p
    def get_password(self, s, u): return self.d.get((s, u))


app.keyring = FakeKeyring()

repo = os.path.join(base, "repo")
A = os.path.join(base, "Аня")           # кирилиця — щоб не втратити покриття
B = os.path.join(base, "borys")
subprocess.run([sc.SVNADMIN,
                "create", repo], check=True, capture_output=True)
# .lstrip: на POSIX шлях уже починається з "/", і без цього вийшло б
# file:////… — svn таке ковтає при checkout, але svn info віддає канонічні три
# слеші, і порівняння URL у probe() каже «тут інший проєкт».
url = "file:///" + repo.replace(os.sep, "/").lstrip("/")

api = app.Api()
api.setup(url, A, "anya", "s3cret")


def inc(a):
    s = a.state(remote=True)
    return s.get("incoming_n"), {i["path"]: i["kind"]
                                 for i in s.get("incoming") or []}


print("=" * 62)
print("1. Порожній проєкт")
print("=" * 62)
n, _ = inc(api)
check("на чистій копії нічого не чекає", n == 0, n)

print()
print("=" * 62)
print("2. ВЛАСНА здача не робить людину «відсталою»")
print("=" * 62)
open(os.path.join(A, "hero.blend"), "wb").write(b"B" * 400)
open(os.path.join(A, "notes.txt"), "w", encoding="utf-8").write("один\n")
api.do_commit(["hero.blend", "notes.txt"], "старт")

n, _ = inc(api)
check("одразу після своєї здачі — нічого не чекає", n == 0, n)

print()
print("=" * 62)
print("3. Чужі зміни видно — з правильним словом")
print("=" * 62)
sc.checkout(url, B)
open(os.path.join(B, "props.blend"), "wb").write(b"P" * 300)
sc.add(B, ["props.blend"])
sc.commit(B, ["props.blend"], "новий реквізит")

os.chmod(os.path.join(B, "notes.txt"), 0o666)
with open(os.path.join(B, "notes.txt"), "a", encoding="utf-8") as fh:
    fh.write("два\n")
sc.commit(B, ["notes.txt"], "дописав")

n, kinds = inc(api)
check("бачимо рівно два вхідні файли", n == 2, (n, kinds))
check("новий файл названо added", kinds.get("props.blend") == "added", kinds)
check("правку названо modified", kinds.get("notes.txt") == "modified", kinds)

print()
print("=" * 62)
print("4. Забрати — і лічильник знову нуль")
print("=" * 62)
api.do_update()
n, kinds = inc(api)
check("після Get latest нічого не чекає", n == 0, (n, kinds))
check("файл справді приїхав", os.path.isfile(os.path.join(A, "props.blend")))

print()
print("=" * 62)
print("5. Видалення на сервері теж рахується")
print("=" * 62)
sc.update(B)
sc.remove(B, ["props.blend"])
sc.commit(B, ["props.blend"], "прибрав реквізит")
n, kinds = inc(api)
check("видалений файл потрапив у список", n == 1, (n, kinds))
check("видалення названо deleted", kinds.get("props.blend") == "deleted", kinds)

print()
print("=" * 62)
print("6. Власні незакомічені правки НЕ рахуються як вхідні")
print("=" * 62)
api.do_update()
os.chmod(os.path.join(A, "notes.txt"), 0o666)
with open(os.path.join(A, "notes.txt"), "a", encoding="utf-8") as fh:
    fh.write("моє\n")
s = api.state(remote=True)
check("своя правка видима у files",
      any(f["path"] == "notes.txt" for f in s["files"]))
check("але вона не в списку до завантаження", s["incoming_n"] == 0,
      s.get("incoming"))

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
