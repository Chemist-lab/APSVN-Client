# -*- coding: utf-8 -*-
"""Історія окремого файлу, відкат до старої версії, повернення видаленого.

Усе на тимчасовому file://-репозиторії. Імена файлів навмисно недобрі:
кирилиця, апостроф U+02BC (немає в жодному ANSI) і '@' у назві — саме на них
ламалися попередні реалізації.
"""
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


import getpass
ME = getpass.getuser()

base = tempfile.mkdtemp(prefix="apsvn_hist_")
sc.ensure_config(os.path.join(base, "appdata"))
repo = os.path.join(base, "repo")
wc = os.path.join(base, "Проєкт Міста")          # кирилиця у шляху копії
subprocess.run([sc.SVNADMIN,
                "create", repo], check=True, capture_output=True)
# .lstrip: на POSIX шлях уже починається з "/", і без цього вийшло б
# file:////… — svn таке ковтає при checkout, але svn info віддає канонічні три
# слеші, і порівняння URL у probe() каже «тут інший проєкт».
url = "file:///" + repo.replace("\\", "/").lstrip("/")
sc.checkout(url, wc)

BLEND = "Сцена міста.blend"                       # кирилиця
AT = "render@2x.blend"                            # '@' — ламав ВСІ --targets
full = os.path.join(wc, BLEND)


def put(name, body):
    p = os.path.join(wc, name)
    if os.path.exists(p):
        os.chmod(p, 0o666)
    with open(p, "wb") as fh:
        fh.write(body)


def take(name):
    sc.lock(wc, [name], me=ME)


V = [b"\x00VERSION-ONE\xff" * 40, b"\x00VERSION-TWO\xff" * 40,
     b"\x00VERSION-THREE\xff" * 40, b"\x00VERSION-FOUR\xff" * 40]

print("=" * 64)
print("0. Імена, на яких ламався --targets")
print("=" * 64)
put(AT, b"AT-FILE" * 10)
try:
    sc.add(wc, [AT])
    r = sc.commit(wc, [AT], "файл з @ у назві")
    check("файл з '@' у назві здається", "commit" in r, r)
except Exception as e:
    check("файл з '@' у назві здається", False, e)
try:
    take(AT)
    check("файл з '@' можна зайняти", True)
except Exception as e:
    check("файл з '@' можна зайняти", False, e)

# set_needs_lock більше не має розгортатися як шаблон
put("побічний.txt", b"not binary")
sc.add(wc, ["побічний.txt"])
sc.commit(wc, ["побічний.txt"], "текстовий побічний файл")
try:
    sc.set_needs_lock(wc, [AT])
    # propget НЕ приймає --targets, тож перевіряємо через -R --xml, як це
    # робить scan_unprotected
    root = sc._xml(["propget", "svn:needs-lock", "-R", "."], cwd=wc, timeout=60)
    marked = {os.path.basename((t.get("path") or "").replace("\\", "/"))
              for t in root.findall("target")}
    check("needs-lock ліг на потрібний файл", AT in marked, sorted(marked))
    check("needs-lock НЕ чіпляється на сторонні файли",
          "побічний.txt" not in marked, sorted(marked))
except Exception as e:
    check("needs-lock НЕ чіпляється на сторонні файли", False, e)

print()
print("=" * 64)
print("1. Історія окремого файлу")
print("=" * 64)
put(BLEND, V[0])
sc.add(wc, [BLEND])
sc.commit(wc, [BLEND], "перший начерк")
for i, body in enumerate(V[1:], start=2):
    take(BLEND)
    put(BLEND, body)
    sc.commit(wc, [BLEND], "правка №%d — українською 🎬" % i)

hist = sc.file_log(wc, BLEND)
check("історія файлу читається", len(hist) == 4, len(hist))
check("найновіша ревізія перша", hist and hist[0]["rev"] > hist[-1]["rev"],
      [h["rev"] for h in hist])
check("опис українською вцілів", any("українською 🎬" in h["msg"] for h in hist),
      [h["msg"] for h in hist])
check("автор проставлений", all(h["author"] == ME for h in hist))
check("дії A/M визначено", hist[-1]["action"] == "A" and hist[0]["action"] == "M",
      [(h["rev"], h["action"]) for h in hist])
check("дата НЕ за Гринвічем (є зсув або збіг)",
      all(len(h["date"]) == 16 for h in hist), [h["date"] for h in hist])
check("is_binary бачить бінарник", sc.is_binary(wc, BLEND) is True)
check("is_binary не плутає текст", sc.is_binary(wc, "побічний.txt") is False)

print()
print("=" * 64)
print("2. Подивитися стару версію, нічого не чіпаючи")
print("=" * 64)
r2 = [h["rev"] for h in hist if h["action"]][-1]
peek = os.path.join(base, "погляд.blend")
try:
    sc.save_revision_as(wc, BLEND, r2, peek)
    got = open(peek, "rb").read()
    check("стара версія вивантажена окремим файлом", got == V[0],
          "%d байт" % len(got))
    check("бойовий файл НЕ змінено", open(full, "rb").read() == V[3])
except Exception as e:
    check("стара версія вивантажена окремим файлом", False, e)

print()
print("=" * 64)
print("3. Відкат до старої версії")
print("=" * 64)
rescue = os.path.join(base, "запас")
try:
    res = sc.restore_revision(wc, BLEND, r2, me=ME, rescue_dir=rescue)
    check("вміст став версією r%s" % r2, open(full, "rb").read() == V[0])
    check("запасну копію зроблено", res["rescue"] and os.path.isfile(res["rescue"]),
          res["rescue"])
    check("у запасі саме те, що було", open(res["rescue"], "rb").read() == V[3])
    st = {f["path"]: f for f in sc.status(wc, me=ME)}
    check("svn бачить це як звичайну зміну",
          st.get(BLEND, {}).get("status") == "modified", st.get(BLEND))
    check("лок лишився за нами", st.get(BLEND, {}).get("lock_mine") is True)
    r = sc.commit(wc, [BLEND], "повернув версію r%s" % r2)
    check("відкат здається звичайним комітом", "commit" in r, r)
    check("історію НЕ переписано — ревізій побільшало",
          len(sc.file_log(wc, BLEND)) == 5, len(sc.file_log(wc, BLEND)))
except Exception as e:
    check("вміст став версією r%s" % r2, False, e)

# сміття після себе лишати не можна
check("тимчасовий .apsvn-part прибрано",
      not os.path.exists(full + ".apsvn-part"))

print()
print("=" * 64)
print("4. Відкат не мовчить, коли файл тримає інший")
print("=" * 64)
wc2 = os.path.join(base, "friend")
sc.checkout(url, wc2)
sc.unlock(wc, [BLEND])
sc.lock(wc2, [BLEND], me=ME)                # інша робоча копія тримає лок
try:
    sc.restore_revision(wc, BLEND, r2, me=ME)
    check("чужий лок зупиняє відкат", False, "відкат пройшов, а не мав")
except sc.SvnError as e:
    check("чужий лок зупиняє відкат", "locked" in str(e).lower(), e)
before = open(full, "rb").read()
check("при відмові файл на диску НЕ зіпсовано", before == V[0])
sc.unlock(wc2, [BLEND])

print()
print("=" * 64)
print("5. Повторний лок власного файлу не лякає людину")
print("=" * 64)
take(BLEND)
try:
    r = sc.lock(wc, [BLEND], me=ME)
    check("повторний лок свого файлу — не помилка", True, r)
except Exception as e:
    check("повторний лок свого файлу — не помилка", False, e)

print()
print("=" * 64)
print("6. Повернення видаленого файлу")
print("=" * 64)
GONE = "звʼязок.blend"                            # апостроф U+02BC
put(GONE, b"DELETED-LATER" * 30)
sc.add(wc, [GONE])
sc.commit(wc, [GONE], "файл, який згодом зникне")
sc.remove(wc, [GONE])
sc.commit(wc, [GONE], "прибрав файл")
sc.purge_deleted(wc, [GONE])
check("файл зник із диска", not os.path.exists(os.path.join(wc, GONE)))

dead = sc.deleted_files(wc)
names = {d["path"] for d in dead}
check("видалений файл знайдено", GONE in names, sorted(names))
check("мотлох у видалених не показується",
      not any(sc.JUNK_RE.search(os.path.basename(n)) for n in names), sorted(names))
entry = next((d for d in dead if d["path"] == GONE), None)
try:
    sc.restore_deleted(wc, GONE, entry["rev"])
    back = os.path.join(wc, GONE)
    check("файл повернувся на диск", os.path.isfile(back))
    check("вміст точний", open(back, "rb").read() == b"DELETED-LATER" * 30)
    r = sc.commit(wc, [GONE], "повернув видалений файл")
    check("повернення здається", "commit" in r, r)
    # copy зберігає звʼязок із минулим: у логу видно і ревізію повернення,
    # і ту, де файл жив до видалення. cat-варіант дав би лише одну.
    hg = sc.file_log(wc, GONE)
    check("історія збереглася (не новий файл з нуля)", len(hg) >= 2,
          [(h["rev"], h["action"]) for h in hg])
    check("видно, звідки файл повернувся",
          any(h.get("renamed_from") for h in hg),
          [(h["rev"], h["action"], h.get("renamed_from")) for h in hg])
    check("у списку видалених його більше немає",
          GONE not in {d["path"] for d in sc.deleted_files(wc)})
except Exception as e:
    check("файл повернувся на диск", False, e)

print()
print("=" * 64)
print("7. Розпізнавання теки перед підключенням проєкту")
print("=" * 64)
empty = os.path.join(base, "порожня")
os.makedirs(empty)
check("порожня тека", sc.probe_dir(empty)["state"] == "empty", sc.probe_dir(empty))
p = sc.probe_dir(wc)
check("своя робоча копія", p["state"] == "wc", p)
check("URL робочої копії видно", (p.get("url") or "").startswith("file:///"), p)
sub = os.path.join(wc, "підтека")
os.makedirs(sub, exist_ok=True)
check("підтека чужої копії розпізнана", sc.probe_dir(sub)["state"] == "subdir",
      sc.probe_dir(sub))
check("неіснуюча тека", sc.probe_dir(os.path.join(base, "нема"))["state"] == "missing")

print()
print("=" * 64)
print("8. Переклад нових помилок")
print("=" * 64)
check("W160042 -> порада оновитись",
      "out of date" in sc.humanize("svn: warning: W160042: Lock failed: newer version of '/a' exists"))
check("E155037 -> Полагодити",
      "Repair" in sc.humanize("svn: E155037: Previous operation has not finished"))
check("E195012 -> про файл, а не про проєкт",
      "did not exist yet" in sc.humanize("svn: E195012: Unable to find repository location"))
check("E155000 -> чужий проєкт у теці",
      "different project" in sc.humanize("svn: E155000: is already a working copy for a different URL"))

print()
print("=" * 64)
print("9. Що змінилось у коміті (права панель History)")
print("=" * 64)
# Свідомо НЕ через `svn diff`: на живому сервері diff одного .blend ішов
# 13 секунд і повертав «Cannot display: file marked as a binary type» —
# svn тягне обидві ревізії через мережу, щоб потім відмовитись показувати.
# `log -v --xml -r N` дає той самий перелік за 0.1 с.
open(os.path.join(wc, "сцена.blend"), "wb").write(b"B" * 300)
open(os.path.join(wc, "нотатки.txt"), "w", encoding="utf-8").write("один\n")
sc.add(wc, ["сцена.blend", "нотатки.txt"])
r_add = sc.COMMIT_RE.search(
    sc.commit(wc, ["сцена.blend", "нотатки.txt"], "два файли")).group(1)

d = sc.revision_files(wc, r_add)
paths = {f["path"]: f for f in d["files"]}
check("віддає обидва файли", d["total"] == 2, d)
check("кирилиця в іменах ціла", "сцена.blend" in paths, list(paths))
check("додавання позначене як A",
      paths.get("сцена.blend", {}).get("action") == "A", paths.get("сцена.blend"))
check("і перекладене людською",
      paths.get("сцена.blend", {}).get("action_text") == "added")
check("шляхи без початкового косого",
      not any(f["path"].startswith("/") for f in d["files"]),
      [f["path"] for f in d["files"]])
check("нічого не обрізано", d["truncated"] is False)

os.chmod(os.path.join(wc, "нотатки.txt"), 0o666)
with open(os.path.join(wc, "нотатки.txt"), "a", encoding="utf-8") as fh:
    fh.write("два\n")
r_mod = sc.COMMIT_RE.search(
    sc.commit(wc, ["нотатки.txt"], "дописав")).group(1)
d = sc.revision_files(wc, r_mod)
check("правка позначена як M",
      d["files"] and d["files"][0]["action"] == "M", d["files"])

sc.remove(wc, ["сцена.blend"])
r_del = sc.COMMIT_RE.search(
    sc.commit(wc, ["сцена.blend"], "прибрав")).group(1)
d = sc.revision_files(wc, r_del)
check("видалення позначене як D",
      d["files"] and d["files"][0]["action"] == "D", d["files"])
check("і перекладене", d["files"][0]["action_text"] == "deleted")

# Коміт-велетень: первинний імпорт проєкту легко дає тисячі шляхів (у справжньому
# репозиторії користувача такий коміт має 2062), малювати їх усі нема сенсу.
os.makedirs(os.path.join(wc, "гурт"), exist_ok=True)
for i in range(60):
    open(os.path.join(wc, "гурт", "f%03d.txt" % i), "w").write("x")
sc.add(wc, ["гурт"])
r_big = sc.COMMIT_RE.search(sc.commit(wc, ["гурт"], "гуртом")).group(1)
d = sc.revision_files(wc, r_big, cap=10)
check("великий коміт обрізано", len(d["files"]) == 10, len(d["files"]))
check("але лічильник каже правду", d["total"] >= 60, d["total"])
check("і про обрізання сказано", d["truncated"] is True)

check("неіснуюча ревізія не валить",
      sc.revision_files(wc, 999999)["files"] == [])
check("сміття замість ревізії не валить",
      sc.revision_files(wc, "abc")["files"] == [])
check("None замість ревізії не валить",
      sc.revision_files(wc, None)["files"] == [])

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
