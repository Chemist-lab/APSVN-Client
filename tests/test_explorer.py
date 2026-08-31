# -*- coding: utf-8 -*-
"""Провідник проєкту: показ, локи, безпека запуску, мініатюри.

Сценарії взято з розбору ризиків. Найважливіші три:
  * шлях мусить бути ВІД КОРЕНЯ копії, інакше однойменний файл із підтеки
    виконав би дію над файлом у корені;
  * запускати можна лише дозволені розширення — тека проєкту лежить на
    мережевій шарі, і .exe/.bat/.lnk звідти не мають запускатися ніколи;
  * файл, зайнятий колегою, і файл, якого ще немає на диску, мусять бути
    видимі — інакше людина вважатиме, що їх не існує.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import explorer as ex
import svn_client as sc
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


import getpass
ME = getpass.getuser()

base = tempfile.mkdtemp(prefix="apsvn_expl_")
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
api.add_project(url, wc, ME, "pw", name="Місто")

# дерево: тека з підтекою, кириличні імена, мотлох, «небезпечні» розширення
os.makedirs(os.path.join(wc, "Кадри", "текстури"), exist_ok=True)
for rel, body in (
        ("Кадри/сцена міста.blend", b"\x00BLEND" * 50),
        ("Кадри/нотатки.txt", "текст".encode("utf-8")),
        ("Кадри/hero.blend1", b"JUNK"),                     # мотлох
        ("Кадри/текстури/wall.png", b"\x89PNG\r\n\x1a\n" + b"x" * 60),
        ("Кадри/setup.exe", b"MZ" + b"\x00" * 40),          # запускати не можна
        ("readme.txt", b"hi"),
):
    with open(os.path.join(wc, rel.replace("/", os.sep)), "wb") as fh:
        fh.write(body)
api.do_commit(["Кадри", "readme.txt"], "перше дерево")

print("=" * 64)
print("1. Корінь: теки й файли, мотлох приховано")
print("=" * 64)
d = api.browse("")
names = [e["name"] for e in d["entries"]]
check("тека видно", "Кадри" in names, names)
check("файл кореня видно", "readme.txt" in names, names)
check("теки стоять перед файлами",
      names.index("Кадри") < names.index("readme.txt"), names)
check("шлях кореня порожній", d["path"] == "", d["path"])
check("у корені немає «вгору»", d["parent"] is None, d["parent"])
kadry = next(e for e in d["entries"] if e["name"] == "Кадри")
check("тека помічена як тека", kadry["kind"] == "dir", kadry["kind"])
check("у теки немає розміру", kadry["size"] is None)

print()
print("=" * 64)
print("2. Підтека: шляхи ВІД КОРЕНЯ, не голі імена")
print("=" * 64)
d = api.browse("Кадри")
by = {e["name"]: e for e in d["entries"]}
check("кириличний файл видно", "сцена міста.blend" in by, sorted(by))
check("шлях від кореня копії",
      by["сцена міста.blend"]["path"] == "Кадри/сцена міста.blend",
      by["сцена міста.blend"]["path"])
check("вкладена тека видно", by.get("текстури", {}).get("kind") == "dir")
check("мотлох Blender приховано", "hero.blend1" not in by, sorted(by))
check("є шлях «вгору»", d["parent"] == "", d["parent"])
check("розмір і дата є",
      by["сцена міста.blend"]["size"] == 300 and by["сцена міста.blend"]["mtime"],
      (by["сцена міста.blend"]["size"], by["сцена міста.blend"]["mtime"]))

d2 = api.browse("Кадри/текстури")
check("третій рівень читається", [e["name"] for e in d2["entries"]] == ["wall.png"],
      [e["name"] for e in d2["entries"]])
check("шлях назад веде на рівень вище", d2["parent"] == "Кадри", d2["parent"])

print()
print("=" * 64)
print("3. Що можна запускати, а що ні")
print("=" * 64)
check(".blend запускається", by["сцена міста.blend"]["openable"] is True)
check(".txt запускається", by["нотатки.txt"]["openable"] is True)
check(".exe НЕ запускається", by["setup.exe"]["openable"] is False, by["setup.exe"])
try:
    api.open_file("Кадри/setup.exe")
    check(".exe відхилено", False, "відкрився, а не мав")
except sc.SvnError as e:
    check(".exe відхилено", "does not open files of this kind" in str(e), e)
for bad in ("shot.lnk", "run.bat", "x.ps1", "a.cmd", "b.scr"):
    check("%-9s не в дозволених" % bad, not bad.lower().endswith(ex.OPENABLE))

print()
print("=" * 64)
print("4. Вихід за межі проєкту неможливий")
print("=" * 64)
for bad in ("..", "../..", "..\\..\\Windows", "Кадри/../..", "C:\\Windows"):
    try:
        ex.inside(wc, bad)
        check("відхилено: %r" % bad, False, "пройшло")
    except sc.SvnError:
        check("відхилено: %r" % bad, True)
check("сам корінь дозволено", ex.inside(wc, "") == os.path.abspath(wc))

print()
print("=" * 64)
print("5. Локи видно, зокрема чужі й на незмінених файлах")
print("=" * 64)
friend = os.path.join(base, "друга")
sc.checkout(url, friend)
sc.lock(friend, ["Кадри/сцена міста.blend"], me=ME)
d = api.browse("Кадри")
by = {e["name"]: e for e in d["entries"]}
f = by["сцена міста.blend"]
check("лок із чужої копії видно", f["lock_owner"] == ME, f)
check("він не вважається нашим", f["lock_mine"] is False, f)
check("файл при цьому НЕ змінений", f["status"] in ("normal", "none"), f["status"])
sc.unlock(friend, ["Кадри/сцена міста.blend"])

api.do_lock(["Кадри/сцена міста.blend"])
by = {e["name"]: e for e in api.browse("Кадри")["entries"]}
check("власний лок помічено як наш", by["сцена міста.blend"]["lock_mine"] is True,
      by["сцена міста.blend"])

print()
print("=" * 64)
print("6. Файл, якого ще немає на диску, все одно видно")
print("=" * 64)
open(os.path.join(friend, "Кадри", "новий-від-колеги.blend"), "wb").write(b"N" * 20)
sc.add(friend, ["Кадри/новий-від-колеги.blend"])
sc.commit(friend, ["Кадри/новий-від-колеги.blend"], "колега додав")
d = api.browse("Кадри")
by = {e["name"]: e for e in d["entries"]}
g = by.get("новий-від-колеги.blend")
check("нескачаний файл показано", g is not None, sorted(by))
if g:
    check("позначено, що його ще немає", g["on_disk"] is False, g)
    check("запускати його не пропонують", g["openable"] is False, g)

print()
print("=" * 64)
print("7. Значок «усередині щось нове» — і чого він НЕ ловить")
print("=" * 64)
d = api.browse("")
kadry = next(e for e in d["entries"] if e["name"] == "Кадри")
check("тека з новим комітом усередині помічена",
      kadry.get("new_inside") is True, kadry)
sc.update(wc, username=ME, password="pw")
d = api.browse("")
kadry = next(e for e in d["entries"] if e["name"] == "Кадри")
check("після оновлення значок зникає", not kadry.get("new_inside"), kadry)
# локи ревізій не створюють, тож із теки їх не видно — це відомо й навмисно
sc.lock(friend, ["Кадри/нотатки.txt"], me=ME)
d = api.browse("")
kadry = next(e for e in d["entries"] if e["name"] == "Кадри")
check("лок усередині теки значка НЕ дає (і це не помилка)",
      not kadry.get("new_inside"), kadry)
sc.unlock(friend, ["Кадри/нотатки.txt"])

print()
print("=" * 64)
print("8. Вкладений проєкт видно й не пропонують відкривати")
print("=" * 64)
nested = os.path.join(wc, "чужий-проєкт")
repo2 = os.path.join(base, "repo2")
subprocess.run([sc.SVNADMIN,
                "create", repo2], check=True, capture_output=True)
sc.checkout("file:///" + repo2.replace("\\", "/"), nested)
d = api.browse("")
n = next((e for e in d["entries"] if e["name"] == "чужий-проєкт"), None)
check("вкладений проєкт у списку є", n is not None)
if n:
    check("помічено як окремий проєкт", n["nested"] is True, n)

print()
print("=" * 64)
print("9. Подробиці й мініатюра")
print("=" * 64)
det = api.file_details("Кадри/нотатки.txt")
check("розмір у подробицях", det["size"] > 0, det["size"])
check("дата у подробицях", bool(det["mtime"]), det["mtime"])
check("для .txt мініатюри немає", det["preview"] is None)
det = api.file_details("Кадри/текстури/wall.png")
check("png не валить провідник", "preview" in det)

# справжній .blend із мініатюрою, якщо такий знайдеться на машині
import glob
real = glob.glob(r"I:\AP-SVN\*.blend")
if real:
    dst = os.path.join(wc, "справжній.blend")
    shutil.copyfile(real[0], dst)
    det = api.file_details("справжній.blend")
    check("мініатюра з .blend витягнута", bool(det["preview"]),
          (det["preview"] or "")[:40])
    check("мініатюра — це data: URI для вебвʼю",
          (det["preview"] or "").startswith("data:image/"), (det["preview"] or "")[:30])
    check("розміри мініатюри відомі", det["preview_w"] and det["preview_h"],
          (det["preview_w"], det["preview_h"]))
else:
    check("мініатюра .blend (пропущено — немає файлу для проби)", True)

print()
print("=" * 64)
print("9b. Зайняти цілу теку")
print("=" * 64)
# Subversion лока на теку не має взагалі — перевіряємо це прямо
try:
    sc.lock(wc, ["Кадри"], me=ME)
    check("лок на саму теку неможливий", False, "пройшов, а не мав")
except sc.SvnError as e:
    check("лок на саму теку неможливий", True, str(e)[:50])

api.do_unlock(["Кадри/сцена міста.blend"])
stats = api.folder_stats("Кадри")
check("рахує файли в теці", stats["total"] >= 3, stats)
check("своїх локів поки немає", stats["mine"] == 0, stats)
check("чужих локів поки немає", stats["others_n"] == 0, stats)

r = api.lock_folder("Кадри")
check("тека зайнята", "Locked" in r, r)
after = api.folder_stats("Кадри")
check("зайнято все, що можна", after["mine"] == after["total"], after)
check("вкладена тека теж під локом",
      all(f["lock_mine"] for f in api.browse("Кадри/текстури")["entries"]
          if f["kind"] == "file" and f["on_disk"]),
      [(f["name"], f["lock_mine"]) for f in api.browse("Кадри/текстури")["entries"]])

print()
print("=" * 64)
print("9c. Частина файлів у колеги: беремо решту й чесно про це кажемо")
print("=" * 64)
api.unlock_folder("Кадри")
sc.update(friend, username=ME, password="pw")
sc.lock(friend, ["Кадри/нотатки.txt"], me=ME)
st = api.folder_stats("Кадри")
check("чужий лок помічено ДО дії", st["others_n"] == 1, st)
r = api.lock_folder("Кадри")
check("решту все одно зайнято", "Locked" in r, r)
check("про пропущені сказано", "could not be locked" in r, r)
a2 = api.folder_stats("Кадри")
check("наших локів менше на один", a2["mine"] == a2["total"] - 1, a2)
sc.unlock(friend, ["Кадри/нотатки.txt"])

print()
print("=" * 64)
print("9d. Відпустити цілу теку")
print("=" * 64)
r = api.unlock_folder("Кадри")
check("теку відпущено", "Released" in r, r)
check("своїх локів не лишилось", api.folder_stats("Кадри")["mine"] == 0)
try:
    api.unlock_folder("Кадри")
    check("повторне відпускання пояснено", False, "пройшло мовчки")
except sc.SvnError as e:
    check("повторне відпускання пояснено", "do not hold anything" in str(e), e)

check("мотлох не потрапляє в лок",
      not any("blend1" in i["path"] for i in sc.files_under(wc, "Кадри")),
      [i["path"] for i in sc.files_under(wc, "Кадри")])
check("теки самі в список на лок не входять",
      all(os.path.isfile(os.path.join(wc, i["path"].replace("/", os.sep)))
          for i in sc.files_under(wc, "Кадри")))

print()
print("=" * 64)
print("10. Провідник відступає, поки триває передача")
print("=" * 64)
api.busy.set()
for fn, args in (("browse", ("",)), ("file_details", ("readme.txt",))):
    try:
        getattr(api, fn)(*args)
        check("%s відступає під час передачі" % fn, False, "пройшло")
    except sc.SvnError as e:
        check("%s відступає під час передачі" % fn, "Please wait" in str(e), e)
api.busy.clear()

print()
print("=" * 64)
print("11. Зникла тека — зрозуміла відмова, не трейсбек")
print("=" * 64)
try:
    api.browse("нема-такої-теки")
    check("зникла тека -> зрозуміла відмова", False, "пройшло")
except sc.SvnError as e:
    check("зникла тека -> зрозуміла відмова", "no longer there" in str(e), e)

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
