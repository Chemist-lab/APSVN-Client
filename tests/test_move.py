# -*- coding: utf-8 -*-
"""Перенос файлів між теками — і все, що може при цьому піти не так.

Перенос у провіднику — це svn move, а не перетягування байтів на диску: так
історія йде за файлом, а сервер переносить за ним і задачу. Звідси й
перевірки: що людина бачить один рядок, а здає обидві половини; що
повернення назад — справжнє «скасувати»; що ім'я, якого немає в кодовій
сторінці Windows, все одно здається; і головне — що перенос, під час якого
колега змінив файл, НЕ з'їдає його роботу.

Плюс те, що навколо: провідник без мережі, перетягування назовні (без
справжньої миші — лише запобіжники) і копіювання шляху.
"""
import getpass
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "app"))
sys.path.insert(0, os.path.join(_ROOT, "vendor"))
import svn_client as sc
import desktop
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_move_")
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
ME = getpass.getuser()
repo = os.path.join(base, "repo")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace(os.sep, "/").lstrip("/")
wc = os.path.join(base, "Проєкт")
api = app.Api()
api.add_project(url, wc, ME, "pw", name="Перенос")

APO = "сценаʼдругa.blend"              # апостроф поза будь-якою ANSI


def put(root, rel, data=b"x"):
    full = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if os.path.exists(full):
        os.chmod(full, 0o666)
    with open(full, "wb") as fh:
        fh.write(data)


def on_disk(rel, root=None):
    return os.path.exists(os.path.join(root or wc, rel.replace("/", os.sep)))


def rows():
    return {f["path"]: f for f in sc.status(wc, me=ME)}


def repo_has(path):
    try:
        sc._run(["info", url + "/" + sc._quote(path)], timeout=60)
        return True
    except sc.SvnError:
        return False


for rel, data in (("Кадри/сцена.blend", b"BLEND-1"), ("Кадри/" + APO, b"BLEND-2"),
                  ("Кадри/render@2x.png", b"PNG"), ("Кадри/sh010/a.blend", b"A"),
                  ("Текстури/wood.png", b"WOOD"), ("Текстури/notes.txt", b"n")):
    put(wc, rel, data)
os.makedirs(os.path.join(wc, "Архів"))
api.do_commit(["Кадри", "Текстури", "Архів"], "проєкт")

print("=" * 66)
print("1. Перенос файлу: один рядок для людини, дві половини для svn")
print("=" * 66)
msg = api.move_items(["Кадри/сцена.blend"], "Архів")
check("перенесено", "Moved “сцена.blend”" in msg, msg)
check("файл справді на новому місці, а старого нема",
      on_disk("Архів/сцена.blend") and not on_disk("Кадри/сцена.blend"))
r = rows()
new, old = r.get("Архів/сцена.blend", {}), r.get("Кадри/сцена.blend", {})
check("нове місце знає, звідки воно", new.get("moved_from") == "Кадри/сцена.blend", new)
check("старе місце знає, куди поїхало", old.get("moved_to") == "Архів/сцена.blend", old)
check("людина читає «moved here»", new.get("status_text") == "moved here", new)
out = api.do_commit(["Архів/сцена.blend"], "у архів")
check("здача ЛИШЕ нового місця проходить — старе додалося само",
      sc.COMMIT_RE.search(out), out)
check("у сховищі — на новому місці", repo_has("Архів/сцена.blend"))
check("у сховищі — і не на старому", not repo_has("Кадри/сцена.blend"))
log = sc.file_log(wc, "Архів/сцена.blend")
check("історія йде за файлом (видно коміт до переносу)",
      len(log) >= 2 and log[-1]["msg"] == "проєкт", [x["msg"] for x in log])
check("після здачі статус чистий", not rows(), rows())

print()
print("=" * 66)
print("2. Ім'я з апострофом U+02BC: здається через заглушку, яку прибирають")
print("=" * 66)
api.move_items(["Кадри/" + APO], "Архів")
out = api.do_commit(["Архів/" + APO], "апостроф")
check("перенос із таким ім'ям здано", sc.COMMIT_RE.search(out), out)
check("заглушки на старому місці не лишилося", not on_disk("Кадри/" + APO))
check("у сховищі — на новому місці", repo_has("Архів/" + APO))

print()
print("=" * 66)
print("3. '@' в імені — не peg-ревізія")
print("=" * 66)
msg = api.move_items(["Кадри/render@2x.png"], "Архів")
check("render@2x.png переїхав", on_disk("Архів/render@2x.png"), msg)
out = api.do_commit(["Архів/render@2x.png"], "@")
check("і здався", sc.COMMIT_RE.search(out), out)

print()
print("=" * 66)
print("4. Назад — справжнє «скасувати»")
print("=" * 66)
api.move_items(["Текстури/wood.png"], "Архів")
m = api.move_back("Архів/wood.png")
check("повернуто", on_disk("Текстури/wood.png") and not on_disk("Архів/wood.png"), m)
check("статус чистий — наче нічого й не було", not rows(), rows())
api.move_items(["Текстури/wood.png"], "Архів")
put(wc, "Архів/wood.png", b"WOOD changed after the move")
api.move_back("Архів/wood.png")
w = rows().get("Текстури/wood.png", {})
check("змінене після переносу повертається зі зміною",
      open(os.path.join(wc, "Текстури", "wood.png"), "rb").read() ==
      b"WOOD changed after the move" and w.get("status") == "modified", w)
api.do_revert(["Текстури/wood.png"])

print()
print("=" * 66)
print("5. Теки: у нову теку, цілу теку, у саму себе")
print("=" * 66)
os.makedirs(os.path.join(wc, "Нова"))
put(wc, "Нова/чернетка.txt", b"draft")
msg = api.move_items(["Текстури/notes.txt"], "Нова")
r = rows()
check("файл переїхав у теку, якої svn ще не знав",
      r.get("Нова/notes.txt", {}).get("moved_from") == "Текстури/notes.txt", msg)
check("сама тека додана", r.get("Нова", {}).get("status") == "added", r.get("Нова"))
check("а її інший вміст — ні (його ніхто не просив здавати)",
      r.get("Нова/чернетка.txt", {}).get("status") != "added", r.get("Нова/чернетка.txt"))
out = api.do_commit(["Нова/notes.txt"], "у нову теку")
check("здача сама взяла нову теку", sc.COMMIT_RE.search(out) and repo_has("Нова/notes.txt"),
      out)
msg = api.move_items(["Кадри/sh010"], "Архів")
check("тека переїхала з вмістом", on_disk("Архів/sh010/a.blend"), msg)
r = rows().get("Архів/sh010", {})
check("перенесена тека в списку — тека (значок), але не «кинута» тека",
      r.get("folder") is True and not r.get("dir"), r)
out = api.do_commit(["Архів/sh010"], "тека")
check("перенос теки здано", sc.COMMIT_RE.search(out) and repo_has("Архів/sh010/a.blend")
      and not repo_has("Кадри/sh010"), out)
try:
    api.move_items(["Архів"], "Архів/sh010")
    check("теку в саму себе — відмова", False)
except sc.SvnError as e:
    check("теку в саму себе — відмова з поясненням", "inside itself" in str(e), e)
check("у ту саму теку — нічого не робимо",
      api.move_items(["Архів/sh010"], "Архів") == "Already there")
put(wc, "Текстури/сцена.blend", b"a namesake")
sc.add(wc, ["Текстури/сцена.blend"])
sc.commit(wc, ["Текстури/сцена.blend"], "тезка")
try:
    api.move_items(["Текстури/сцена.blend"], "Архів")
    check("тезку не затираємо", False)
except sc.SvnError as e:
    check("тезку в теці призначення не затираємо", "already has a file" in str(e), e)
put(wc, "нове.txt", b"new")
msg = api.move_items(["нове.txt"], "Архів")
check("нове (невідоме svn) переноситься просто на диску",
      on_disk("Архів/нове.txt") and rows().get("Архів/нове.txt", {}).get("status")
      == "unversioned", msg)

print()
print("=" * 66)
print("6. Лок: свій їде, чужий — ні")
print("=" * 66)
friend = os.path.join(base, "колега")
sc.checkout(url, friend)
sc.lock(friend, ["Текстури/wood.png"], username="olena")
api.state(remote=True)                   # синхронізація: чужий лок тепер відомий
try:
    api.move_items(["Текстури/wood.png"], "Архів")
    check("файл під чужим локом не переносимо", False)
except sc.SvnError as e:
    check("файл під чужим локом не переносимо — і кажемо чий",
          "olena is working on it" in str(e), e)
check("він лишився на місці", on_disk("Текстури/wood.png"))
sc.unlock(friend, ["Текстури/wood.png"], username="olena")
api.state(remote=True)
api.do_lock(["Текстури/wood.png"])
msg = api.move_items(["Текстури/wood.png"], "Архів")
check("свій лок: переносимо й попереджаємо, що лок лишиться на старому місці",
      "Your lock stays with the old place" in msg, msg)
out = api.do_commit(["Архів/wood.png"], "з локом")
check("перенос файлу під своїм локом здано", sc.COMMIT_RE.search(out), out)

print()
print("=" * 66)
print("7. Я переношу — колега тим часом змінює: його робота не губиться")
print("=" * 66)
sc.update(friend)
put(wc, "Кадри/sh020.blend", b"v1")
sc.add(wc, ["Кадри/sh020.blend"])
sc.commit(wc, ["Кадри/sh020.blend"], "sh020")
sc.update(friend)
api.move_items(["Кадри/sh020.blend"], "Архів")
sc.lock(friend, ["Кадри/sh020.blend"], username="olena")
put(friend, "Кадри/sh020.blend", b"v2 - olena's day of work")
sc.commit(friend, ["Кадри/sh020.blend"], "olena", username="olena", keep_locks=False)
try:
    api.do_commit(["Архів/sh020.blend"], "перенос")
    check("здача переносу поверх чужої зміни не проходить", False)
except sc.SvnError as e:
    check("здача переносу поверх чужої зміни не проходить (застаріло)", True, e)
api.do_update()
r = rows()
c = r.get("Кадри/sh020.blend", {})
check("конфлікт упізнано як «змінили, поки ти переносив»",
      c.get("status") == "conflicted" and c.get("conflict_kind") == "moved", c)
api.do_resolve(["Кадри/sh020.blend"], True, "mine")
check("«лишити мій перенос» — зміна колеги у файлі на новому місці",
      open(os.path.join(wc, "Архів", "sh020.blend"), "rb").read() ==
      b"v2 - olena's day of work")
out = api.do_commit(["Архів/sh020.blend"], "перенос після конфлікту")
check("…і перенос здано", sc.COMMIT_RE.search(out), out)
got = sc._dec(sc._run(["cat", url + "/" + sc._quote("Архів/sh020.blend")], timeout=60))
check("у сховищі на новому місці — робота колеги, а не стара версія",
      got == "v2 - olena's day of work", got)

# і другий вихід — «повернути як було»
put(wc, "Кадри/sh030.blend", b"v1")
sc.add(wc, ["Кадри/sh030.blend"])
sc.commit(wc, ["Кадри/sh030.blend"], "sh030")
sc.update(friend)
api.move_items(["Кадри/sh030.blend"], "Архів")
put(wc, "Архів/sh030.blend", b"my edit after the move")
sc.lock(friend, ["Кадри/sh030.blend"], username="olena")
put(friend, "Кадри/sh030.blend", b"v2 olena")
sc.commit(friend, ["Кадри/sh030.blend"], "olena", username="olena", keep_locks=False)
api.do_update()
before = set(os.listdir(app.RESCUE)) if os.path.isdir(app.RESCUE) else set()
api.do_resolve(["Кадри/sh030.blend"], False, "theirs")
r = rows()
check("«повернути як було» — файл на старому місці, з роботою колеги",
      open(os.path.join(wc, "Кадри", "sh030.blend"), "rb").read() == b"v2 olena")
check("на новому місці нічого не лишилося", not on_disk("Архів/sh030.blend"))
check("статус чистий", not {k: v for k, v in r.items()
                            if "sh030" in k}, r)
saved = set(os.listdir(app.RESCUE)) - before
check("моя копія з нового місця — у «Safety copies»",
      any(n.endswith("sh030.blend") for n in saved) and
      open(os.path.join(app.RESCUE, [n for n in saved if n.endswith("sh030.blend")][0]),
           "rb").read() == b"my edit after the move", saved)

print()
print("=" * 66)
print("8. Провідник: без мережі, з останньою синхронізацією")
print("=" * 66)
api.move_items(["Архів/render@2x.png"], "Кадри")      # версійований — svn move
api.state(remote=True)
d = api.browse("Кадри")
by = {e["name"]: e for e in d["entries"]}
moved_here = [e for e in d["entries"] if e.get("moved_from")]
check("перенесене в теку позначено «moved here»",
      moved_here and moved_here[0]["status_text"] == "moved here",
      [(e["name"], e["status_text"]) for e in d["entries"]])
put(friend, "Кадри/від-колеги.png", b"PNG")
sc.add(friend, ["Кадри/від-колеги.png"])
sc.commit(friend, ["Кадри/від-колеги.png"], "колега", username="olena")
check("до синхронізації нового від колеги ще не видно",
      "від-колеги.png" not in {e["name"] for e in api.browse("Кадри")["entries"]})
api.state(remote=True)
g = {e["name"]: e for e in api.browse("Кадри")["entries"]}.get("від-колеги.png")
check("після синхронізації — «not downloaded yet»",
      g and g["on_disk"] is False and g["status_text"] == "not downloaded yet", g)
root = {e["name"]: e for e in api.browse("")["entries"]}
check("у корені тека «Кадри» знає, що всередині нове",
      root["Кадри"].get("new_inside") is True, root["Кадри"])
check("…і що там моя нездана робота", root["Кадри"].get("mine_inside") is True,
      root["Кадри"])

print()
print("=" * 66)
print("9. Перетягування назовні: запобіжники без справжньої миші")
print("=" * 66)
check("без вікна перетягування не вдаємо", api.drag_supported() is False)
check("drag_out без вікна — «unsupported», а не виняток",
      api.drag_out(["Архів/sh020.blend"]) == "unsupported")
if desktop.WINDOWS:
    full = api.full_paths(["Архів/sh020.blend", "Архів/" + APO])
    data = desktop.file_drop_data(full)
    from System.Windows.Forms import DataFormats
    back = list(data.GetData(DataFormats.FileDrop))
    check("у перетягуванні — справжні файли (CF_HDROP), з кирилицею й U+02BC",
          back == full, back)
    check("і шляхи текстом — для будь-якого поля введення",
          str(data.GetData(DataFormats.UnicodeText)) == "\r\n".join(full))

    class FakeForm:
        called = False

        def DoDragDrop(self, *a):
            FakeForm.called = True
            return 1

    # Кнопка миші зараз відпущена — саме той випадок, коли OLE «кинув» би
    # файл туди, де курсор. Запобіжник мусить не почати перетягування зовсім.
    # Кнопка тут справжня: якщо людина саме клацає, поки йде тест, запобіжник
    # чесно пропускає — тоді перевірку пропускаємо й ми (як із буфером вище).
    from System.Windows.Forms import Control, MouseButtons
    if int(Control.MouseButtons) & int(MouseButtons.Left):
        print("  (ліву кнопку миші зараз натиснуто — перевірку пропущено)")
    else:
        r = desktop._drag_on_ui(FakeForm(), full)
        check("кнопку вже відпущено — перетягування не починається",
              r == "cancelled" and not FakeForm.called, r)
else:
    check("поза Windows нативного перетягування немає", not desktop.drag_supported(None))

print()
print("=" * 66)
print("10. Копіювання шляху")
print("=" * 66)
was = desktop.read_clipboard_text()
if desktop.WINDOWS and was is None:
    print("  (у буфері не текст — не чіпаємо його, перевірку пропущено)")
else:
    try:
        m = api.copy_paths(["Архів/" + APO])
        got = desktop.read_clipboard_text()
        check("у буфері — повний шлях, з U+02BC", got == os.path.join(wc, "Архів", APO),
              (m, got))
        api.copy_paths(["Архів/sh020.blend", "Архів/render@2x.png"])
        got = desktop.read_clipboard_text() or ""
        check("кілька — по одному в рядку", got.splitlines() == api.full_paths(
            ["Архів/sh020.blend", "Архів/render@2x.png"]), got)
    finally:
        if was is not None:
            desktop.copy_text(was)          # повернути людині її буфер
try:
    api.copy_paths(["../../Windows/win.ini"])
    check("шлях поза проєктом не копіюється", False)
except sc.SvnError:
    check("шлях поза проєктом не копіюється", True)

print()
print("=" * 66)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 66)
shutil.rmtree(base, ignore_errors=True)
sys.exit(1 if FAIL else 0)
