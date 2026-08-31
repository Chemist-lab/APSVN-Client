# -*- coding: utf-8 -*-
"""Смоук по шару app.Api — тому, що реально смикає інтерфейс."""
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
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


# не чіпаємо ані справжній конфіг, ані сховище паролів Windows
base = tempfile.mkdtemp(prefix="apsvn_api_")
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
wc = os.path.join(base, "Мій Проєкт")
subprocess.run([sc.SVNADMIN, "create", repo],
               check=True, capture_output=True)
url = "file:///" + repo.replace("\\", "/")

api = app.Api()
check("до підключення state() каже 'не налаштовано'", api.state().get("configured") is False)

# --- підключення -----------------------------------------------------------
try:
    api.setup(url, wc, "anya", "s3cret")
    check("setup пройшов", os.path.isdir(os.path.join(wc, ".svn")))
except Exception as e:
    check("setup пройшов", False, e)

s = api.state(remote=True)
check("state() бачить проєкт", s.get("configured") is True, s.get("error"))
check("state() віддає ревізію", s.get("info", {}).get("revision") is not None, s.get("info"))
check("логін підхопився з keyring", s.get("me") == "anya")

# --- новий файл -> здати ---------------------------------------------------
open(os.path.join(wc, "hero.blend"), "wb").write(b"B" * 400)
open(os.path.join(wc, "hero.blend1"), "wb").write(b"junk")
s = api.state()
paths = {f["path"] for f in s["files"]}
check("новий файл видно", "hero.blend" in paths, paths)
check("мотлох Blender не показано", "hero.blend1" not in paths, paths)

try:
    r = api.do_commit(["hero.blend"], "перша сцена")
    check("здача нового файлу", "commit" in r, r)
except Exception as e:
    check("здача нового файлу", False, e)

# --- захист: правка бінарника без лока не доходить до сервера --------------
os.chmod(os.path.join(wc, "hero.blend"), 0o666)
with open(os.path.join(wc, "hero.blend"), "ab") as fh:
    fh.write(b"CHANGED")
try:
    api.do_commit(["hero.blend"], "правка без лока")
    check("правку без лока відхилено ДО передачі", False, "коміт пройшов, а не мав")
except sc.SvnError as e:
    check("правку без лока відхилено ДО передачі",
          "Lock these before submitting" in str(e), e)

# --- лок -> здача проходить -------------------------------------------------
try:
    api.do_lock(["hero.blend"])
    st = {f["path"]: f for f in api.state()["files"]}
    check("після зайняття файл позначено як мій", st["hero.blend"]["lock_mine"] is True, st["hero.blend"])
    r = api.do_commit(["hero.blend"], "правка під локом")
    check("здача під локом проходить", "commit" in r, r)
except Exception as e:
    check("здача під локом проходить", False, e)

# --- мотлох не можна здати навіть примусово --------------------------------
try:
    api.do_commit(["hero.blend1"], "спроба здати мотлох")
    check("мотлох Blender неможливо здати", False, "пройшло, а не мало")
except sc.SvnError as e:
    check("мотлох Blender неможливо здати",
          "temporary copies are never submitted" in str(e), e)

# --- зникнення файлу -> видалення ------------------------------------------
# лок уже спав під час здачі — відпускати нема чого
try:
    api.do_unlock(["hero.blend"])
except sc.SvnError:
    pass
os.chmod(os.path.join(wc, "hero.blend"), 0o666)
os.unlink(os.path.join(wc, "hero.blend"))
try:
    r = api.do_commit(["hero.blend"], "прибрав сцену")
    check("зниклий файл здається як видалення", "commit" in r, r)
except Exception as e:
    check("зниклий файл здається як видалення", False, e)

# --- історія ---------------------------------------------------------------
lg = api.get_log()
check("історія читається", len(lg) >= 3, len(lg))
check("описи українською вціліли", any(e["msg"] == "перша сцена" for e in lg),
      [e["msg"] for e in lg])

# --- порожній опис ---------------------------------------------------------
try:
    api.do_commit(["hero.blend"], "   ")
    check("порожній опис відхилено", False, "пройшло")
except sc.SvnError as e:
    check("порожній опис відхилено", "Write" in str(e), e)


# --- лок після здачі --------------------------------------------------------
# Типово лок СПАДАЄ: так просив користувач і так поводиться svn. Зворотний бік
# реальний — файл із svn:needs-lock одразу стає read-only, тож про це має бути
# сказано в тості, і має лишатися спосіб поводитись інакше.
open(os.path.join(wc, "лок-тест.blend"), "wb").write(b"L" * 100)
api.do_commit(["лок-тест.blend"], "новий файл")
api.do_lock(["лок-тест.blend"])
os.chmod(os.path.join(wc, "лок-тест.blend"), 0o666)
with open(os.path.join(wc, "лок-тест.blend"), "ab") as fh:
    fh.write(b"X")
r = api.do_commit(["лок-тест.blend"], "правка під локом")
check("здача пройшла", "commit" in r, r)
st_now = {f["path"]: f for f in sc.status(wc, me="anya")}
check("лок СПАВ після здачі",
      not st_now.get("лок-тест.blend", {}).get("lock_mine"), st_now.get("лок-тест.blend"))
check("про read-only попереджено", "read-only again" in r, r)
check("файл справді став read-only",
      not os.access(os.path.join(wc, "лок-тест.blend"), os.W_OK))

# а з увімкненим перемикачем — лишається
api.do_lock(["лок-тест.blend"])
os.chmod(os.path.join(wc, "лок-тест.blend"), 0o666)
with open(os.path.join(wc, "лок-тест.blend"), "ab") as fh:
    fh.write(b"Y")
r = api.do_commit(["лок-тест.blend"], "ще правка", keep_locks=True)
st_now = {f["path"]: f for f in sc.status(wc, me="anya")}
check("з перемикачем лок лишається",
      st_now.get("лок-тест.blend", {}).get("lock_mine") is True, st_now.get("лок-тест.blend"))
check("і про це сказано", "stays locked" in r, r)
api.do_unlock(["лок-тест.blend"])

# налаштування памʼятається і працює без явного аргументу
api.set_pref("keep_locks", True)
api.do_lock(["лок-тест.blend"])
os.chmod(os.path.join(wc, "лок-тест.blend"), 0o666)
with open(os.path.join(wc, "лок-тест.blend"), "ab") as fh:
    fh.write(b"Z")
r = api.do_commit(["лок-тест.blend"], "за налаштуванням")
st_now = {f["path"]: f for f in sc.status(wc, me="anya")}
check("налаштування keep_locks діє без аргументу",
      st_now.get("лок-тест.blend", {}).get("lock_mine") is True, r)
api.set_pref("keep_locks", False)
api.do_unlock(["лок-тест.blend"])

# --- усі перепони одразу ----------------------------------------------------
# З появою «виділити все» людина позначає десятки файлів. Відмова по одній
# перетворилася б на десятки заходів, тому коміт мусить назвати все відразу.
open(os.path.join(wc, "нове1.blend"), "wb").write(b"N" * 50)
open(os.path.join(wc, "нове2.blend"), "wb").write(b"N" * 50)
api.do_commit(["нове1.blend", "нове2.blend"], "два нових")
for n in ("нове1.blend", "нове2.blend"):
    os.chmod(os.path.join(wc, n), 0o666)
    with open(os.path.join(wc, n), "ab") as fh:
        fh.write(b"CHANGED")
open(os.path.join(wc, "мотлох.blend1"), "wb").write(b"J")
try:
    api.do_commit(["нове1.blend", "нове2.blend", "мотлох.blend1"], "усе разом")
    check("перепони названо одразу", False, "коміт пройшов, а не мав")
except sc.SvnError as e:
    t = str(e)
    check("названо обидва файли без лока", "нове1.blend" in t and "нове2.blend" in t, t)
    check("названо і мотлох у тому ж повідомленні", "мотлох.blend1" in t, t)
    check("перепони згруповано за причиною",
          t.count("temporary copies") == 1 and t.count("Lock these") == 1, t)

# --- зникла тека проєкту ---------------------------------------------------
# НЕ майстер підключення: інакше разом із ним зникає єдиний шлях повернутися
# в робочий проєкт, і людина починає качати сотні гігабайтів заново
api.c["wc"] = os.path.join(base, "нема-такої")
s = api.state()
check("зникла тека -> зрозуміле пояснення, а не трейсбек", bool(s.get("broken")), s.get("broken"))
check("проєкт лишається у списку", s.get("configured") is True)

print()
print("=" * 62)
print("Відкат вибраних файлів просто з історії")
print("=" * 62)
api.c["wc"] = wc                  # попередній блок навмисно «зламав» шлях
# Найлегша помилка тут — на одну ревізію. Файл, ВИДАЛЕНИЙ у коміті N, у самому
# N уже не існує: брати його треба з N-1. Інакше «поверни мені його» відповідає
# «file not found», і це виглядає як поламана програма.
open(os.path.join(wc, "props.blend"), "wb").write(b"V1" * 100)
open(os.path.join(wc, "list.txt"), "w", encoding="utf-8").write("перший\n")
api.do_commit(["props.blend", "list.txt"], "перша версія")

api.do_lock(["props.blend"])
open(os.path.join(wc, "props.blend"), "wb").write(b"V2" * 100)
os.chmod(os.path.join(wc, "list.txt"), 0o666)
open(os.path.join(wc, "list.txt"), "w", encoding="utf-8").write("другий\n")
r2 = api.do_commit(["props.blend", "list.txt"], "друга версія")
rev2 = sc.COMMIT_RE.search(r2).group(1)

# ---- відкат зміненого файлу до попереднього стану
files = api.revision_files(rev2)["files"]
check("revision_files через Api віддає обидва", len(files) == 2, files)

before = int(rev2) - 1
msg = api.restore_many(before, [{"path": "props.blend", "action": "M"}])
check("відкат одного файлу проходить", "brought back" in msg, msg)
check("на диску знову перша версія",
      open(os.path.join(wc, "props.blend"), "rb").read() == b"V1" * 100)
check("сказано, що це ще НЕ на сервері", "NOT on the server" in msg, msg)
check("рятувальна копія зроблена",
      os.path.isdir(app.RESCUE) and os.listdir(app.RESCUE), app.RESCUE)

# ---- пачкою
api.do_commit(["props.blend"], "повернув першу")
open(os.path.join(wc, "list.txt"), "w", encoding="utf-8").write("третій\n")
api.do_commit(["list.txt"], "третій")
msg = api.restore_many(before, [{"path": "list.txt", "action": "M"},
                                {"path": "props.blend", "action": "M"}])
check("пачка з двох повертається", "2 files brought back" in msg, msg)
check("текстовий файл теж повернувся",
      open(os.path.join(wc, "list.txt"), encoding="utf-8").read().strip() == "перший",
      open(os.path.join(wc, "list.txt"), encoding="utf-8").read())

# ---- ВИДАЛЕНИЙ файл: беремо з коміту ПЕРЕД видаленням
api.do_commit(["list.txt", "props.blend"], "вирівняв")
os.chmod(os.path.join(wc, "list.txt"), 0o666)
api.do_remove(["list.txt"]) if hasattr(api, "do_remove") else None
if os.path.exists(os.path.join(wc, "list.txt")):
    sc.remove(wc, ["list.txt"])
rdel = sc.COMMIT_RE.search(
    sc.commit(wc, ["list.txt"], "видалив список")).group(1)
# svn delete у нас іде з --keep-local, тож байти ЛИШАЮТЬСЯ на диску,
# а svn про них більше не знає. Це й є той випадок, на якому логіка
# «файл на місці, отже перезапишемо» ламалась.
st_now = {f["path"]: f["status"] for f in sc.status(wc)}
check("після видалення svn його більше не знає",
      st_now.get("list.txt") == "unversioned", st_now.get("list.txt"))
check("але байти лишились на диску (--keep-local)",
      os.path.isfile(os.path.join(wc, "list.txt")))

d = api.revision_files(rdel)
act = {f["path"]: f["action"] for f in d["files"]}
check("у коміті видалення дія позначена D", act.get("list.txt") == "D", act)

# ключове: передаємо САМ коміт видалення, а не попередній —
# restore_many має сам відняти одиницю
msg = api.restore_many(rdel, [{"path": "list.txt", "action": "D"}])
check("видалений файл повертається", "brought back" in msg, msg)
check("і він знову на диску",
      os.path.isfile(os.path.join(wc, "list.txt")), msg)

# ---- запобіжники
# Найважливіший із них: файл із НЕЗДАНИМИ змінами. Відкотити його — значить
# знищити роботу, якої більше ніде немає. Перевіряємо саме версійований і
# саме змінений файл: на невідомому svn файлі спрацював би зовсім інший
# запобіжник, і ця перевірка проходила б, нічого не доводячи.
open(os.path.join(wc, "робочий.txt"), "w", encoding="utf-8").write("здане\n")
sc.add(wc, ["робочий.txt"])
api.do_commit(["робочий.txt"], "здав робочий")
os.chmod(os.path.join(wc, "робочий.txt"), 0o666)
open(os.path.join(wc, "робочий.txt"), "w",
     encoding="utf-8").write("півдня роботи\n")
try:
    api.restore_many(before, [{"path": "робочий.txt", "action": "M"}])
    check("файл із незданими змінами не затирається", False, "пройшло")
except sc.SvnError as e:
    check("файл із незданими змінами не затирається",
          "unsubmitted changes" in str(e), e)
check("і робота лишилась на місці",
      open(os.path.join(wc, "робочий.txt"),
           encoding="utf-8").read().strip() == "півдня роботи")

open(os.path.join(wc, "draft.txt"), "w", encoding="utf-8").write("нове\n")
try:
    api.restore_many(before, [{"path": "draft.txt", "action": "M"}])
    check("невідомий svn файл теж не відкочується мовчки", False, "пройшло")
except sc.SvnError as e:
    check("невідомий svn файл теж не відкочується мовчки",
          "Nothing was brought back" in str(e), e)

try:
    api.restore_many(before, [])
    check("порожній вибір відхиляється", False, "пройшло")
except sc.SvnError as e:
    check("порожній вибір відхиляється", "Nothing was picked" in str(e), e)

try:
    api.restore_many("не число", [{"path": "props.blend", "action": "M"}])
    check("сміття замість номера коміту відхиляється", False, "пройшло")
except sc.SvnError as e:
    check("сміття замість номера коміту відхиляється",
          "cannot be read" in str(e), e)

msg = None
try:
    msg = api.restore_many(before, [{"path": "props.blend", "action": "M"},
                                    {"path": "draft.txt", "action": "M"}])
except sc.SvnError as e:
    msg = str(e)
check("один поганий файл не зриває решту пачки",
      "brought back" in (msg or "") and "Left alone" in (msg or ""), msg)

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
