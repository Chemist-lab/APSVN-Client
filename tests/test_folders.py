# -*- coding: utf-8 -*-
"""Художник перетягнув у проєкт ТЕКУ з файлами.

Так буває щодня, і саме тут APSVN показував один рядок замість файлів, а
спроба здати їх падала сирою англійською помилкою.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import svn_client as sc
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_fold_")
app.CONF_DIR = os.path.join(base, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.LOG = os.path.join(app.CONF_DIR, "error.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")
os.makedirs(app.CONF_DIR, exist_ok=True)


class FakeKeyring:
    def __init__(self): self.d = {}
    def set_password(self, s, u, p): self.d[(s, u)] = p
    def get_password(self, s, u): return self.d.get((s, u))


app.keyring = FakeKeyring()

repo = os.path.join(base, "repo")
wc = os.path.join(base, "Проєкт Міста")
subprocess.run([sc.SVNADMIN,
                "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace("\\", "/")

api = app.Api()
api.add_project(url, wc, "anya", "s3cret", name="Місто")

# художник перетягнув теку з кадрами, вкладеною текою і мотлохом Blender
D = "Кадри міста"
os.makedirs(os.path.join(wc, D, "текстури"), exist_ok=True)
for n in ("сцена.blend", "hero.blend", "нотатки.txt"):
    open(os.path.join(wc, D, n), "wb").write(b"X" * 100)
open(os.path.join(wc, D, "hero.blend1"), "wb").write(b"JUNK")   # мотлох
open(os.path.join(wc, D, "текстури", "wall.png"), "wb").write(b"P" * 100)

print("=" * 64)
print("1. Тека видно як тека — з лічильником вмісту")
print("=" * 64)
files = api.state()["files"]
paths = {f["path"] for f in files}
check("рядок теки є", D in paths, sorted(paths))
row = next(f for f in files if f["path"] == D)
check("позначено як теку", row.get("dir") is True, row)
check("порахувало файли (мотлох не рахуємо)", row.get("n_files") == 4, row)
check("порахувало обсяг", row.get("bytes", 0) > 0, row.get("bytes"))
check("порахувало все, без обрізання", row.get("counted_all") is True, row)
check("тисячі рядків у список НЕ висипалися",
      not any(p.startswith(D + "/") for p in paths), sorted(paths))

print()
print("=" * 64)
print("1b. Розгортання показує вміст на вимогу")
print("=" * 64)
inner = api.list_new_folder(D)
names = {f["path"] for f in inner["files"]}
check("файл із теки видно", D + "/сцена.blend" in names, sorted(names))
check("файл із ВКЛАДЕНОЇ теки видно", D + "/текстури/wall.png" in names, sorted(names))
check("мотлох Blender приховано", D + "/hero.blend1" not in names, sorted(names))
check("нічого не обрізано", inner["truncated"] is False)
check("бінарність визначено",
      next(f for f in inner["files"] if f["path"] == D + "/сцена.blend")["binary"] is True)

print()
print("=" * 64)
print("2. Здача файлів із нової теки проходить БЕЗ окремого клопоту")
print("=" * 64)
sel = [D + "/сцена.blend", D + "/текстури/wall.png"]
try:
    r = api.do_commit(sel, "перші кадри")
    check("коміт пройшов, теку додано самі", "commit" in r, r)
except Exception as e:
    check("коміт пройшов, теку додано самі", False, e)

# Дивимось на СЕРВЕР, а не на копію: після коміту з файловими цілями
# корінь робочої копії лишається на старій ревізії, і `list .` порожній.
# І саме --xml, бо текстовий вивід svn друкує в cp1251 — кирилиця в ньому
# перетворюється на «Êàäðè ì³ñòà».
def repo_listing():
    root = sc._xml(["list", "-R", url], cwd=wc, timeout=60)
    return " | ".join(e.findtext("name") or "" for e in root.iter("entry"))

listing = repo_listing()
check("тека створена в репозиторії", D in listing, listing.replace("\n", " | "))
check("вкладена тека теж", "текстури" in listing, listing.replace("\n", " | "))
check("здано саме вибране", "сцена.blend" in listing and "wall.png" in listing)
check("невибране НЕ поїхало", "hero.blend" not in listing.replace("hero.blend1", ""),
      listing.replace("\n", " | "))
check("мотлох у репозиторій не потрапив", "blend1" not in listing)

print()
print("=" * 64)
print("3. Решта файлів тієї ж теки здається окремо")
print("=" * 64)
rest = [D + "/hero.blend", D + "/нотатки.txt"]
try:
    r = api.do_commit(rest, "решта кадрів")
    check("другий коміт у вже існуючу теку", "commit" in r, r)
except Exception as e:
    check("другий коміт у вже існуючу теку", False, e)

print()
print("=" * 64)
print("4. Дуже велика тека: рядок той самий, список обрізається")
print("=" * 64)
BIG = "Гора"
os.makedirs(os.path.join(wc, BIG), exist_ok=True)
for i in range(sc.LIST_CAP + 20):
    open(os.path.join(wc, BIG, "f%04d.txt" % i), "wb").write(b"x")
files = api.state()["files"]
row = next(f for f in files if f["path"] == BIG)
check("велика тека — теж один рядок", row.get("dir") is True, row)
check("файли порахувало", row.get("n_files") == sc.LIST_CAP + 20, row.get("n_files"))
big = api.list_new_folder(BIG)
check("список обрізано до межі", len(big["files"]) == sc.LIST_CAP, len(big["files"]))
check("про обрізання сказано", big["truncated"] is True)

print()
print("=" * 64)
print("5. Порожня тека лишається окремим рядком")
print("=" * 64)
os.makedirs(os.path.join(wc, "Порожня"), exist_ok=True)
paths = {f["path"] for f in api.state()["files"]}
check("порожню теку видно", "Порожня" in paths, sorted(paths))

print()
print("=" * 64)
print("7. Поступ при здачі ЦІЛОЇ теки рахує правильно")
print("=" * 64)
# Позначено ОДИН рядок (теку), а svn звітує про кожен файл усередині. Раніше
# це давало «файл 2062 з 1 (100%)».
W = "Пачка"
os.makedirs(os.path.join(wc, W, "всередині"), exist_ok=True)
for i in range(12):
    open(os.path.join(wc, W, "к%02d.blend" % i), "wb").write(b"B" * 40)
for i in range(5):
    open(os.path.join(wc, W, "всередині", "t%02d.png" % i), "wb").write(b"P" * 40)
open(os.path.join(wc, W, "смітник.blend1"), "wb").write(b"J")   # мотлох не рахуємо

seen = []
api._tick = lambda e: seen.append(e)
r = api.do_commit([W], "ціла тека одним рядком")
check("коміт цілої теки пройшов", "commit" in r, r)
counting = [e for e in seen if e["phase"] in ("prepare", "files")]
check("поступ надходив", len(counting) > 10, len(counting))
tot = {e["total"] for e in counting}
check("загальна кількість одна й та сама", len(tot) == 1, tot)
check("це НЕ кількість вибраних рядків", tot != {1}, tot)
# 12 + 5 файлів + тека + вкладена тека = 19; мотлох не рахується
check("порахувало файли РАЗОМ з теками", tot == {19}, tot)
check("лічильник ніколи не перевищує загальну кількість",
      all(e["done"] <= e["total"] for e in counting),
      [(e["done"], e["total"]) for e in counting[-3:]])
check("відсотки не перевищують 100",
      all((e["pct"] or 0) <= 100 for e in counting))
check("дійшло рівно до кінця", counting[-1]["done"] == 19, counting[-1])
check("мотлох не поїхав", "blend1" not in repo_listing())
api._tick = app.Api._tick.__get__(api)

print()
print("=" * 64)
print("6. Переклад помилки про незгадану теку")
print("=" * 64)
raw = ("svn: E200009: Commit failed (details follow):\n"
       "svn: E200009: 'C:\\wc\\Kadry' is not known to exist in the repository "
       "and is not part of the commit, yet its child is part of the commit")
check("E200009 пояснено людською мовою", "folder" in sc.humanize(raw), sc.humanize(raw))

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
