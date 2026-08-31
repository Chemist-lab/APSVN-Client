# -*- coding: utf-8 -*-
"""Конфлікти всіх видів — і команди, які з них РЕАЛЬНО виводять.

Аудит показав, що APSVN бачив лише один вид конфлікту з чотирьох. Решта три
svn тримає в ОКРЕМИХ атрибутах XML, а в item лишає мирне значення — тож
художник бачив звичайний зелений рядок, ставив галочку, тиснув Submit і
отримував відмову без жодної кнопки, щоб її виправити.

Друга, гірша знахідка: навіть якби ті рядки показали, дві наявні кнопки їх не
вирішували б. `--accept mine-full` і `theirs-full` на деревʼяному конфлікті
НЕ РОБЛЯТЬ НІЧОГО — svn мовчки лишає файл у конфлікті. Тому кожна перевірка
нижче не лише дивиться на статус, а й доводить, що після натискання кнопки
конфлікту більше немає і файл можна здати.

Усе встановлено дослідом на живому репозиторії, не з документації.
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


ADMIN = os.path.join(os.path.dirname(sc.SVN), "svnadmin.exe")
ROOT = tempfile.mkdtemp(prefix="apsvn_conf_")


class Scene:
    """Двоє людей і спільний репозиторій. A — «колега», B — «наш художник»."""

    def __init__(self, tag):
        self.base = os.path.join(ROOT, tag)
        os.makedirs(self.base)
        repo = os.path.join(self.base, "repo")
        subprocess.run([ADMIN, "create", repo], check=True, capture_output=True)
        self.url = "file:///" + repo.replace(os.sep, "/")
        self.A = os.path.join(self.base, "A")
        self.B = os.path.join(self.base, "B")
        sc.checkout(self.url, self.A)
        self.put(self.A, "seed.txt", b"seed")
        sc.add(self.A, ["seed.txt"])
        sc.commit(self.A, ["seed.txt"], "seed")
        sc.checkout(self.url, self.B)

    def put(self, wc, rel, data):
        full = os.path.join(wc, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if os.path.exists(full):
            os.chmod(full, 0o666)
        with open(full, "wb") as fh:
            fh.write(data)

    def read(self, wc, rel):
        full = os.path.join(wc, rel.replace("/", os.sep))
        return open(full, "rb").read() if os.path.isfile(full) else None

    def update_b(self):
        try:
            return sc.update(self.B)
        except Exception as e:
            return str(e)

    def row(self, rel):
        for i in sc.status(self.B, me="borys"):
            if i["path"] == rel:
                return i
        return {}

    def in_conflict(self):
        raw = sc._dec(sc._run(["status", "--xml"], cwd=self.B, timeout=60))
        return ("tree-conflicted" in raw or 'props="conflicted"' in raw
                or 'item="conflicted"' in raw)

    def can_submit(self, rel):
        try:
            sc.commit(self.B, [rel], "після вирішення")
            return True
        except Exception:
            return False


# =====================================================================
print("=" * 66)
print("1. Текстовий конфлікт — те, що працювало й має працювати далі")
print("=" * 66)
s1 = Scene("text")
s1.put(s1.A, "notes.txt", "рядок\n".encode("utf-8"))
sc.add(s1.A, ["notes.txt"])
sc.commit(s1.A, ["notes.txt"], "старт")
sc.update(s1.B)
s1.put(s1.A, "notes.txt", "версія колеги\n".encode("utf-8"))
sc.commit(s1.A, ["notes.txt"], "колега")
s1.put(s1.B, "notes.txt", "моя версія\n".encode("utf-8"))
s1.update_b()
r = s1.row("notes.txt")
check("текстовий конфлікт видно", r.get("status") == "conflicted", r)
check("вид визначено як text", r.get("conflict_kind") == "text", r)
check("сміття .mine/.rN у списку немає",
      not any(i["path"].endswith((".mine",)) or ".r" in i["path"][-4:]
              for i in sc.status(s1.B)),
      [i["path"] for i in sc.status(s1.B)])

# =====================================================================
print()
print("=" * 66)
print("2. Ручне зведення більше не викидається")
print("=" * 66)
s1.put(s1.B, "notes.txt", "колега + я\n".encode("utf-8"))
sc.resolve_conflict(s1.B, "notes.txt", "text", "working")
check("після «I sorted it out myself» лишилось саме зведене",
      s1.read(s1.B, "notes.txt") == "колега + я\n".encode("utf-8"),
      s1.read(s1.B, "notes.txt"))
check("конфлікту більше немає", not s1.in_conflict())
check("і файл можна здати", s1.can_submit("notes.txt"))

s1b = Scene("text2")
s1b.put(s1b.A, "n.txt", b"base\n")
sc.add(s1b.A, ["n.txt"])
sc.commit(s1b.A, ["n.txt"], "b")
sc.update(s1b.B)
s1b.put(s1b.A, "n.txt", b"THEIRS\n")
sc.commit(s1b.A, ["n.txt"], "a")
s1b.put(s1b.B, "n.txt", b"MINE\n")
s1b.update_b()
s1b.put(s1b.B, "n.txt", b"HAND-MERGED\n")
sc.resolve_conflict(s1b.B, "n.txt", "text", "mine")
check("а «keep my version» так само повертає доконфліктне (це навмисне)",
      s1b.read(s1b.B, "n.txt") == b"MINE\n", s1b.read(s1b.B, "n.txt"))

# =====================================================================
print()
print("=" * 66)
print("3. ДЕРЕВʼЯНИЙ конфлікт: колега видалив файл, я його правив")
print("=" * 66)
s2 = Scene("tree")
s2.put(s2.A, "shot.txt", b"base")
sc.add(s2.A, ["shot.txt"])
sc.commit(s2.A, ["shot.txt"], "старт")
sc.update(s2.B)
sc.remove(s2.A, ["shot.txt"])
sc.commit(s2.A, ["shot.txt"], "колега видалив")
s2.put(s2.B, "shot.txt", b"MY WORK")
s2.update_b()
r = s2.row("shot.txt")
check("деревʼяний конфлікт більше не показується як 'added'",
      r.get("status") == "conflicted", r)
check("вид визначено як tree", r.get("conflict_kind") == "tree", r)
check("напис каже про переміщення/видалення",
      "moved or deleted" in (r.get("status_text") or ""), r.get("status_text"))
check("сирий стан svn збережено для розбору",
      r.get("wc_item") == "added", r)

# Доводимо, що СТАРІ кнопки цей конфлікт не вирішували. Найгірше тут
# не сама відмова, а її текст: «choose whose version to keep» у відповідь на
# щойно зроблений вибір. Людина тисне ще раз, і ще, і так до консолі.
for old_choice in ("mine-full", "theirs-full"):
    try:
        sc.resolve(s2.B, ["shot.txt"], old_choice)
        check("СТАРА кнопка (%s) не виводить із tree" % old_choice,
              s2.in_conflict(), "пройшла без помилки й вирішила — svn змінив поведінку")
    except sc.SvnError as e:
        check("СТАРА кнопка (%s) не виводить із tree" % old_choice,
              s2.in_conflict(), "відмова: " + str(e))

sc.resolve_conflict(s2.B, "shot.txt", "tree", "mine")
check("«keep my file» вирішує", not s2.in_conflict())
check("мій файл лишився зі своїм вмістом",
      s2.read(s2.B, "shot.txt") == b"MY WORK")
check("і його можна здати", s2.can_submit("shot.txt"))

s3 = Scene("tree2")
s3.put(s3.A, "shot.txt", b"base")
sc.add(s3.A, ["shot.txt"])
sc.commit(s3.A, ["shot.txt"], "старт")
sc.update(s3.B)
sc.remove(s3.A, ["shot.txt"])
sc.commit(s3.A, ["shot.txt"], "колега видалив")
s3.put(s3.B, "shot.txt", b"MY WORK")
s3.update_b()
sc.resolve_conflict(s3.B, "shot.txt", "tree", "theirs")
check("«take what the team has» вирішує", not s3.in_conflict())
check("файл зник, як і в решти команди",
      not os.path.isfile(os.path.join(s3.B, "shot.txt")))

# =====================================================================
print()
print("=" * 66)
print("4. ПЕРЕШКОДА: мій файл на місці того, що приїжджає")
print("=" * 66)
s4 = Scene("obstruct")
s4.put(s4.A, "render.png", b"TEAM-RENDER")
sc.add(s4.A, ["render.png"])
sc.commit(s4.A, ["render.png"], "колега залив рендер")
s4.put(s4.B, "render.png", b"MY-OWN-RENDER")
s4.update_b()
r = s4.row("render.png")
check("перешкоду більше не підписано 'deleted'",
      r.get("status") == "conflicted", r)
check("вид визначено як obstructed",
      r.get("conflict_kind") == "obstructed", r)
check("напис пояснює, що це МІЙ файл заважає",
      "in the way" in (r.get("status_text") or ""), r.get("status_text"))
check("мої байти на диску цілі",
      s4.read(s4.B, "render.png") == b"MY-OWN-RENDER")
sc.resolve_conflict(s4.B, "render.png", "obstructed", "mine")
check("«keep my file» вирішує перешкоду", not s4.in_conflict())
check("і лишає саме мої байти",
      s4.read(s4.B, "render.png") == b"MY-OWN-RENDER")

s5 = Scene("obstruct2")
s5.put(s5.A, "render.png", b"TEAM-RENDER")
sc.add(s5.A, ["render.png"])
sc.commit(s5.A, ["render.png"], "колега залив")
s5.put(s5.B, "render.png", b"MY-OWN-RENDER")
s5.update_b()
sc.resolve_conflict(s5.B, "render.png", "obstructed", "theirs")
check("«take what the team has» вирішує перешкоду", not s5.in_conflict())
check("і на диску тепер командний файл",
      s5.read(s5.B, "render.png") == b"TEAM-RENDER")

# =====================================================================
print()
print("=" * 66)
print("5. Конфлікт ВЛАСТИВОСТЕЙ")
print("=" * 66)
s6 = Scene("prop")
s6.put(s6.A, "t.txt", b"x")
sc.add(s6.A, ["t.txt"])
sc.commit(s6.A, ["t.txt"], "старт")
sc.update(s6.B)
sc._run(["propset", "svn:mime-type", "text/theirs", "t.txt"],
        cwd=s6.A, timeout=60)
sc.commit(s6.A, ["t.txt"], "колега")
sc._run(["propset", "svn:mime-type", "text/mine", "t.txt"],
        cwd=s6.B, timeout=60)
s6.update_b()
r = s6.row("t.txt")
check("конфлікт властивостей видно", r.get("status") == "conflicted", r)
check("вид визначено як prop", r.get("conflict_kind") == "prop", r)
check(".prej у списку не світиться",
      not any(i["path"].endswith(".prej") for i in sc.status(s6.B)),
      [i["path"] for i in sc.status(s6.B)])
sc.resolve_conflict(s6.B, "t.txt", "prop", "mine")
check("вирішується", not s6.in_conflict())

# =====================================================================
print()
print("=" * 66)
print("6. Жоден вид конфлікту не можна здати")
print("=" * 66)
for tag, mk in (("tree", "tree"), ("obstructed", "obstructed")):
    sx = Scene("nosubmit_" + tag)
    if mk == "tree":
        sx.put(sx.A, "f.txt", b"base")
        sc.add(sx.A, ["f.txt"])
        sc.commit(sx.A, ["f.txt"], "s")
        sc.update(sx.B)
        sc.remove(sx.A, ["f.txt"])
        sc.commit(sx.A, ["f.txt"], "del")
        sx.put(sx.B, "f.txt", b"mine")
    else:
        sx.put(sx.A, "f.txt", b"team")
        sc.add(sx.A, ["f.txt"])
        sc.commit(sx.A, ["f.txt"], "add")
        sx.put(sx.B, "f.txt", b"mine")
    sx.update_b()
    check("%s: сервер відмовляє у здачі" % tag, not sx.can_submit("f.txt"))
    check("%s: інтерфейс блокує ще до сервера" % tag,
          sx.row("f.txt").get("status") == "conflicted", sx.row("f.txt"))

# =====================================================================
print()
print("=" * 66)
print("7. Рятувальна копія перед знищенням")
print("=" * 66)
s7 = Scene("rescue")
s7.put(s7.A, "n.txt", b"base\n")
sc.add(s7.A, ["n.txt"])
sc.commit(s7.A, ["n.txt"], "b")
sc.update(s7.B)
s7.put(s7.A, "n.txt", b"THEIRS\n")
sc.commit(s7.A, ["n.txt"], "a")
s7.put(s7.B, "n.txt", b"MINE-A-WHOLE-DAY\n")
s7.update_b()
rdir = os.path.join(ROOT, "rescue_out")
saved = sc.rescue_copy(s7.B, "n.txt", rdir)
check("копія створюється", saved and os.path.isfile(saved), saved)
sc.resolve_conflict(s7.B, "n.txt", "text", "theirs")
check("після «взяти чуже» на диску версія колеги",
      s7.read(s7.B, "n.txt") == b"THEIRS\n")
# Саме «містить», а не «дорівнює»: для текстового конфлікту svn переписує
# робочий файл маркерами, і робота художника лежить усередині них. Вимога —
# «її можна дістати», а не «файл байт у байт».
check("а моя робота достається з теки порятунку",
      any(b"MINE-A-WHOLE-DAY" in open(os.path.join(rdir, f), "rb").read()
          for f in os.listdir(rdir)),
      os.listdir(rdir))
check("копії немає для неіснуючого файлу",
      sc.rescue_copy(s7.B, "no-such-file.txt", rdir) is None)

# =====================================================================
print()
print("=" * 66)
print("8. Локи накривають те, що справді редагують художники")
print("=" * 66)
for e in (".uasset", ".umap", ".ma", ".mb", ".max", ".hip", ".nk", ".spp",
          ".ztl", ".c4d", ".blend", ".psd"):
    check("needs-lock вішається на %s" % e, e in sc.BINARY_EXT)
check("auto-props справді містить Unreal",
      "*.uasset = svn:needs-lock=*" in sc.CONFIG_BODY)
check("те, що зводиться текстом, локами не душимо",
      not any(e in sc.BINARY_EXT for e in (".txt", ".json", ".xml", ".py")))

# =====================================================================
print()
print("=" * 66)
print("9. Шар Api: рятує й вибирає правильну команду сам")
print("=" * 66)
s8 = Scene("api")
app.CONF_DIR = os.path.join(ROOT, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.LOG = os.path.join(app.CONF_DIR, "error.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")


class FakeKeyring:
    def __init__(self): self.d = {}
    def set_password(self, s, u, p): self.d[(s, u)] = p
    def get_password(self, s, u): return self.d.get((s, u))


app.keyring = FakeKeyring()
s8.put(s8.A, "shot.txt", b"base")
sc.add(s8.A, ["shot.txt"])
sc.commit(s8.A, ["shot.txt"], "s")
sc.update(s8.B)
sc.remove(s8.A, ["shot.txt"])
sc.commit(s8.A, ["shot.txt"], "колега видалив")
s8.put(s8.B, "shot.txt", b"MY WORK")
s8.update_b()

api = app.Api()
api.setup(s8.url, s8.B, "borys", "pw")
files = {f["path"]: f for f in api.state()["files"]}
check("Api віддає конфлікт інтерфейсу",
      files.get("shot.txt", {}).get("status") == "conflicted", files.keys())
check("і вид конфлікту разом із ним",
      files.get("shot.txt", {}).get("conflict_kind") == "tree",
      files.get("shot.txt"))
try:
    api.do_commit(["shot.txt"], "спроба здати конфлікт")
    check("Api не дає здати конфлікт", False, "коміт пройшов, а не мав")
except sc.SvnError as e:
    check("Api не дає здати конфлікт", "conflict" in str(e).lower(), e)

msg = api.do_resolve(["shot.txt"], True)
check("do_resolve сам обрав команду для деревʼяного конфлікту",
      not s8.in_conflict(), msg)
check("і сказав про рятувальну копію", "Safety copies" in msg, msg)
check("копія справді лежить",
      os.path.isdir(app.RESCUE) and os.listdir(app.RESCUE),
      app.RESCUE)

shutil.rmtree(ROOT, ignore_errors=True)
print()
print("=" * 66)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 66)
sys.exit(1 if FAIL else 0)
