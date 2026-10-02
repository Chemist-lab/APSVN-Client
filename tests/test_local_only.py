# -*- coding: utf-8 -*-
"""«Files not on the server»: усе в теці проєкту, чого немає на сервері.

Changes навмисно ховає мотлох і ігнороване, а нові теки показує одним
рядком. Тут — на тимчасовому file://-сховищі з усім, що буває в житті:
  * нове: файл і тека з кадрами (рядок на теку, з кількістю й розміром);
  * резервні копії Blender (.blend1, .blend2) — і поруч зі сценою, і в новій
    теці; тимчасове й системне; desktop.ini і залишки відкритого конфлікту
    svn — показані, але до Кошика не йдуть;
  * ігнороване правилами svn (svn:ignore); вкладена копія іншого проєкту;
  * Кошик: лише мотлох, лише дозволений, перелік — наново на боці програми,
    нове не чіпається ніколи. Сам Кошик Windows тут підмінено (не смітити
    в справжній) — його перевірено вручну, див. desktop.to_recycle_bin.
"""
import getpass
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import svn_client as sc
import desktop
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


ME = getpass.getuser()
base = tempfile.mkdtemp(prefix="apsvn_local_")
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


def put(rel, size=10, wc=None):
    full = os.path.join(wc or WC, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(b"x" * size)
    return full


repo = os.path.join(base, "repo")
WC = os.path.join(base, "Проєкт")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
api = app.Api()
api.add_project(url_of(repo), WC, ME, "pw", name="Проєкт")

# що є на сервері: сцена, текст для конфлікту, правило ігнорувати cache
put("Assets/сцена.blend", 5000)
put("notes.txt", 5)
sc.add(WC, ["Assets", "notes.txt"])
subprocess.run([sc.SVN, "propset", "svn:ignore", "cache", ".", "--non-interactive"],
               cwd=WC, capture_output=True, check=True)
sc.commit(WC, ["Assets", "notes.txt", "."], "r1")

# конфлікт: колега змінив notes.txt, ти теж — після оновлення висить конфлікт
other = os.path.join(base, "колега")
sc.checkout(url_of(repo), other)
with open(os.path.join(other, "notes.txt"), "w") as fh:
    fh.write("their line\n")
sc.commit(other, ["notes.txt"], "r2")
with open(os.path.join(WC, "notes.txt"), "w") as fh:
    fh.write("my line\n")
subprocess.run([sc.SVN, "update", "--non-interactive", "--accept", "postpone"],
               cwd=WC, capture_output=True)
arts = sorted(n for n in os.listdir(WC) if n.startswith("notes.txt."))

# усе, чого на сервері немає
put("Assets/сцена.blend1", 4000)
put("Assets/сцена.blend2", 3000)
put("new.png", 700)
for i in range(3):
    put("Renders/test/frame_%04d.png" % i, 100)
put("Renders/test/old.blend1", 2500)
put("Assets/save.tmp", 30)
put("Assets/Thumbs.db", 20)
put("Assets/desktop.ini", 15)
put("cache/sim/a.vdb", 900)
put("cache/sim/b.vdb", 900)
nested = os.path.join(base, "nested-repo")
subprocess.run([sc.SVNADMIN, "create", nested], check=True, capture_output=True)
sc.checkout(url_of(nested), os.path.join(WC, "Other"))

print("=" * 64)
print("1. Групи, розміри, найважче зверху")
print("=" * 64)
check("конфлікт справді висить і має залишки", len(arts) >= 2, arts)
d = api.local_only()
G = {g["id"]: g for g in d["groups"]}
check("п'ять груп у сталому порядку",
      [g["id"] for g in d["groups"]] == ["new", "backups", "temp", "ignored", "nested"])
new = {r["path"]: r for r in G["new"]["rows"]}
check("нове: файл і тека одним рядком (кадри — без мотлоху всередині)",
      set(new) == {"new.png", "Renders/"} and new["Renders/"]["files"] == 3 and
      new["Renders/"]["bytes"] == 300 and new["new.png"]["bytes"] == 700, new)
check("найважче зверху", [r["path"] for r in G["new"]["rows"]] == ["new.png", "Renders/"])
bk = [r["path"] for r in G["backups"]["rows"]]
check("резервні копії Blender — і поруч зі сценою, і в новій теці, за розміром",
      bk == ["Assets/сцена.blend1", "Assets/сцена.blend2", "Renders/test/old.blend1"]
      and G["backups"]["bytes"] == 9500 and G["backups"]["recyclable"] == 3, bk)
tmp = {r["path"]: r["recyclable"] for r in G["temp"]["rows"]}
check("тимчасове: .tmp і Thumbs.db — у Кошик можна",
      tmp.get("Assets/save.tmp") is True and tmp.get("Assets/Thumbs.db") is True, tmp)
check("desktop.ini — показано, але лишається (налаштування теки Windows)",
      tmp.get("Assets/desktop.ini") is False, tmp)
check("залишки відкритого конфлікту — показано, але лишаються",
      all(tmp.get(a) is False for a in arts), {a: tmp.get(a) for a in arts})
ign = {r["path"]: r for r in G["ignored"]["rows"]}
check("ігнороване правилом svn — теку одним рядком",
      set(ign) == {"cache/"} and ign["cache/"]["files"] == 2 and
      ign["cache/"]["bytes"] == 1800, ign)
check("вкладена копія іншого проєкту — окремо, без обходу",
      [r["path"] for r in G["nested"]["rows"]] == ["Other"], G["nested"]["rows"])
check("підсумок — сума груп", d["files"] == sum(g["files"] for g in d["groups"]) and
      d["bytes"] == sum(g["bytes"] for g in d["groups"]), (d["files"], d["bytes"]))
part = sc.local_only(WC, cap=2)
pb = next(g for g in part["groups"] if g["id"] == "backups")
check("обмеження рядків: два найважчі й «і ще 1»",
      len(pb["rows"]) == 2 and pb["more"] == 1 and pb["files"] == 3, pb)
changes = {f["path"] for f in sc.status(WC)}
check("Changes, як і раніше, мотлоху й ігнорованого не показує",
      not any(p.endswith((".blend1", ".blend2", ".tmp", "Thumbs.db")) or
              p.startswith("cache") for p in changes), sorted(changes))

print()
print("=" * 64)
print("2. Кошик: лише мотлох, лише дозволений, перелік — наново")
print("=" * 64)
binned = []
real_bin = desktop.to_recycle_bin


def fake_bin(paths):
    """Замість Кошика Windows — тека тесту (і перелік того, що туди пішло)."""
    trash = os.path.join(base, "bin")
    os.makedirs(trash, exist_ok=True)
    for i, p in enumerate(paths):
        binned.append(p)
        shutil.move(p, os.path.join(trash, "%03d-%s" % (len(binned), os.path.basename(p))))
    return []


desktop.to_recycle_bin = fake_bin
try:
    out = api.recycle_junk("backups")
    check("резервні копії — у Кошику, з підсумком",
          out == "Moved 3 files (9.3 KB) to the Recycle Bin." and
          not os.path.exists(os.path.join(WC, "Assets", "сцена.blend1")) and
          not os.path.exists(os.path.join(WC, "Renders", "test", "old.blend1")), out)
    check("сама сцена й кадри — на місці",
          os.path.getsize(os.path.join(WC, "Assets", "сцена.blend")) == 5000 and
          len(os.listdir(os.path.join(WC, "Renders", "test"))) == 3)
    binned.clear()
    out = api.recycle_junk("temp")
    names = sorted(os.path.basename(p) for p in binned)
    check("тимчасове — у Кошику лише дозволене",
          names == ["Thumbs.db", "save.tmp"], (out, names))
    check("desktop.ini і залишки конфлікту — на місці",
          os.path.exists(os.path.join(WC, "Assets", "desktop.ini")) and
          all(os.path.exists(os.path.join(WC, a)) for a in arts))
    try:
        api.recycle_junk("new")
        check("нове в Кошик не йде ніколи", False)
    except sc.SvnError:
        check("нове в Кошик не йде ніколи", os.path.exists(os.path.join(WC, "new.png")))
    out = api.recycle_junk("backups")
    check("вдруге — чесне «нема чого»", out == "There is nothing to move to the Recycle Bin.", out)
    put("Assets/сцена.blend1", 4000)
    desktop.to_recycle_bin = lambda paths: list(paths)        # Кошика немає / відмова
    out = api.recycle_junk("backups")
    check("не вийшло — так і сказано, файл на місці",
          "Nothing was moved" in out and "1 file stayed where it was" in out and
          os.path.exists(os.path.join(WC, "Assets", "сцена.blend1")), out)
finally:
    desktop.to_recycle_bin = real_bin
with open(app.ACTIVITY, encoding="utf-8") as fh:
    log = fh.read()
check("у журналі — що й скільки прибрано",
      "recycle Проєкт backups: 3 file(s), 9.3 KB" in log, log.strip().splitlines()[-3:])

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
