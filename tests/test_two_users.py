# -*- coding: utf-8 -*-
"""Сценарії на двох людей: вкрадений лок і конфлікт."""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import svn_client as sc

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_2u_")
sc.ensure_config(os.path.join(base, "appdata"))
repo = os.path.join(base, "repo")
A = os.path.join(base, "Аня")          # кирилиця — щоб не втратити покриття
B = os.path.join(base, "borys")
subprocess.run([sc.SVNADMIN, "create", repo],
               check=True, capture_output=True)
# .lstrip: на POSIX шлях уже починається з "/", і без цього вийшло б
# file:////… — svn таке ковтає при checkout, але svn info віддає канонічні три
# слеші, і порівняння URL у probe() каже «тут інший проєкт».
url = "file:///" + repo.replace("\\", "/").lstrip("/")

import getpass
me = getpass.getuser()

sc.checkout(url, A)
open(os.path.join(A, "hero.blend"), "wb").write(b"B" * 500)
open(os.path.join(A, "notes.txt"), "w", encoding="utf-8").write("рядок один\n")
sc.add(A, ["hero.blend", "notes.txt"])
sc.commit(A, ["hero.blend", "notes.txt"], "старт")
sc.checkout(url, B)

print("=" * 62)
print("1. Вкрадений лок")
print("=" * 62)
sc.lock(A, ["hero.blend"])
st = {i["path"]: i for i in sc.status(A, remote=True, me=me)}
h = st.get("hero.blend", {})
check("свіжий лок = мій (зі звіркою з сервером)", h.get("lock_mine") is True and not h.get("lock_stale"), h)

# хтось із адмінправами зняв лок на сервері
sc._run(["unlock", "--force", url + "/hero.blend"], timeout=60)

st = {i["path"]: i for i in sc.status(A, remote=True, me=me)}
h = st.get("hero.blend", {})
check("знятий на сервері лок видно як ЧУЖУЖИЙ/зниклий", h.get("lock_mine") is False, h)
check("рядок не зник зі списку (інакше людина нічого не побачить)", bool(h), st)
check("піднято прапорець lock_stale", h.get("lock_stale") is True, h)

# без звірки локальний стан лишається оптимістичним — і це нормально
st = {i["path"]: i for i in sc.status(A, remote=False, me=me)}
check("без звірки stale не вигадується", st.get("hero.blend", {}).get("lock_stale") is False,
      st.get("hero.blend"))

print()
print("=" * 62)
print("2. Конфлікт у текстовому файлі")
print("=" * 62)
with open(os.path.join(B, "notes.txt"), "w", encoding="utf-8") as fh:
    fh.write("версія Бориса\n")
sc.commit(B, ["notes.txt"], "правка Бориса")
with open(os.path.join(A, "notes.txt"), "w", encoding="utf-8") as fh:
    fh.write("версія Ані\n")
r = sc.update(A, )
check("update попереджає про конфлікт", "conflict" in r.lower(), r)
st = {i["path"]: i for i in sc.status(A, me=me)}
check("файл позначено як conflicted", st.get("notes.txt", {}).get("status") == "conflicted", st.get("notes.txt"))
check("український підпис КОНФЛІКТ", st.get("notes.txt", {}).get("status_text") == "CONFLICT")

# кнопка «взяти версію колеги»
sc.resolve(A, ["notes.txt"], "theirs-full")
st = {i["path"]: i for i in sc.status(A, me=me)}
body = open(os.path.join(A, "notes.txt"), encoding="utf-8").read()
check("конфлікт знято", st.get("notes.txt", {}).get("status") in (None, "normal"), st.get("notes.txt"))
check("узято саме версію колеги", "Бориса" in body, repr(body))
mess = [f for f in os.listdir(A) if ".mine" in f or ".r" in f]
check("мотлох конфлікту прибрано з диска", not mess, mess)

print()
print("=" * 62)
print("3. Мотлох конфлікту не потрапляє в список")
print("=" * 62)
open(os.path.join(A, "notes.txt.mine"), "w").write("x")
open(os.path.join(A, "notes.txt.r2"), "w").write("x")
paths = {i["path"] for i in sc.status(A, me=me)}
check(".mine приховано", "notes.txt.mine" not in paths, paths)
check(".r2 приховано", "notes.txt.r2" not in paths, paths)

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
