# -*- coding: utf-8 -*-
"""Наскрізний тест svn_client: кирилиця, локи, мотлох, видалення, конфлікти."""
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


base = tempfile.mkdtemp(prefix="apsvn_full_")
appdata = os.path.join(base, "appdata")
repo = os.path.join(base, "repo")
# робоча копія з КИРИЛИЧНОЮ назвою — саме тут падав старий код
wc = os.path.join(base, "Робота Проєкт")

svnadmin = os.path.join(os.path.dirname(sc.SVN), "svnadmin.exe")
subprocess.run([svnadmin, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace("\\", "/")

print("svn:", sc.SVN)
print("ANSI codepage:", sc._acp())
print("repo:", url)
print("wc:  ", wc)
print()

cfg = sc.ensure_config(appdata)
check("config-dir створено", os.path.isfile(os.path.join(cfg, "config")))
check("auto-props у конфігу", "svn:needs-lock" in open(os.path.join(cfg, "config"), encoding="utf-8").read())

# 1. checkout у кириличну теку
try:
    r = sc.checkout(url, wc)
    check("checkout у кириличну теку", os.path.isdir(os.path.join(wc, ".svn")), r)
except Exception as e:
    check("checkout у кириличну теку", False, e)

# 2. файли: звичайний, кириличний, і мотлох
open(os.path.join(wc, "hero.blend"), "wb").write(b"BLENDER" * 1000)
open(os.path.join(wc, "Сцена міста.blend"), "wb").write(b"BLENDER" * 1000)
open(os.path.join(wc, "hero.blend1"), "wb").write(b"JUNK" * 1000)
open(os.path.join(wc, "notes.txt"), "w", encoding="utf-8").write("текст")

st = sc.status(wc)
paths = {i["path"] for i in st}
check("бачить звичайний файл", "hero.blend" in paths, sorted(paths))
check("бачить кириличний файл", "Сцена міста.blend" in paths, sorted(paths))
check("МОТЛОХ .blend1 приховано", "hero.blend1" not in paths, sorted(paths))

# 3. add + commit з УКРАЇНСЬКИМ повідомленням
MSG = "анімація стрибка sh010 — перша чернетка 🎬"
try:
    sc.add(wc, ["hero.blend", "Сцена міста.blend", "notes.txt"])
    r = sc.commit(wc, ["hero.blend", "Сцена міста.blend", "notes.txt"], MSG)
    check("commit пройшов", "commit 1" in r, r)
    check("відповідь про коміт українською", "Committed" not in r, r)
except Exception as e:
    check("commit пройшов", False, e)

# 4. НАЙГОЛОВНІШЕ: чи вціліло повідомлення
lg = sc.log(wc)
got = lg[0]["msg"] if lg else ""
check("УКРАЇНСЬКЕ повідомлення вціліло", got == MSG, repr(got))
check("у повідомленні немає '?'", "?" not in got, repr(got))

# 5. auto-props: чи навісився svn:needs-lock
try:
    out = sc._dec(sc._run(["propget", "svn:needs-lock", "hero.blend"], cwd=wc))
    check("svn:needs-lock навісився автоматично", out.strip() == "*", repr(out.strip()))
except Exception as e:
    check("svn:needs-lock навісився автоматично", False, e)

# 6. locks з правильним визначенням власника
me = None
try:
    import getpass
    me = getpass.getuser()
    sc.lock(wc, ["hero.blend"])
    st = {i["path"]: i for i in sc.status(wc, me=me)}
    h = st.get("hero.blend", {})
    check("лок бачиться як МІЙ", h.get("lock_mine") is True, h)
    check("власник лока правильний", h.get("lock_owner") == me, h.get("lock_owner"))
    sc.unlock(wc, ["hero.blend"])
except Exception as e:
    check("лок бачиться як МІЙ", False, e)

# 7. лок на КИРИЛИЧНОМУ файлі (шлях через targets-файл)
try:
    sc.lock(wc, ["Сцена міста.blend"])
    st = {i["path"]: i for i in sc.status(wc, me=me)}
    check("лок на кириличному файлі", st.get("Сцена міста.blend", {}).get("lock_mine") is True,
          st.get("Сцена міста.blend"))
    sc.unlock(wc, ["Сцена міста.blend"])
except Exception as e:
    check("лок на кириличному файлі", False, e)

# 8. видалений з диска файл -> remove -> commit
os.unlink(os.path.join(wc, "notes.txt"))
st = {i["path"]: i for i in sc.status(wc)}
check("зниклий файл має статус missing", st.get("notes.txt", {}).get("status") == "missing", st.get("notes.txt"))
try:
    sc.remove(wc, ["notes.txt"])
    r = sc.commit(wc, ["notes.txt"], "прибрав нотатки")
    check("коміт видалення пройшов", "commit 2" in r, r)
except Exception as e:
    check("коміт видалення пройшов", False, e)

# 9. read-only захист + revert (правильний цикл: спершу лок)
ro = False
try:
    with open(os.path.join(wc, "hero.blend"), "ab") as fh:
        fh.write(b"X")
except PermissionError:
    ro = True
check("needs-lock зробив файл READ-ONLY (захист від затирання)", ro)
sc.lock(wc, ["hero.blend"])
with open(os.path.join(wc, "hero.blend"), "ab") as fh:
    fh.write(b"CHANGED")
st = {i["path"]: i for i in sc.status(wc)}
check("зміна помічена", st.get("hero.blend", {}).get("status") == "modified", st.get("hero.blend"))
try:
    sc.revert(wc, ["hero.blend"])
    st = {i["path"]: i for i in sc.status(wc, me=me)}
    h = st.get("hero.blend", {})
    check("revert повернув як було", h.get("status") in (None, "normal"), h)
    sc.unlock(wc, ["hero.blend"])
except Exception as e:
    check("revert повернув як було", False, e)

# 10. чесний результат порожнього коміту
try:
    r = sc.commit(wc, ["hero.blend"], "нічого не змінював")
    check("порожній коміт чесно каже правду", "Nothing was sent" in r, r)
except Exception as e:
    check("порожній коміт чесно каже правду", False, e)

# 11. cleanup і переклад помилок
try:
    check("cleanup працює", "repaired" in sc.cleanup(wc))
except Exception as e:
    check("cleanup працює", False, e)
check("переклад E155004", "Repair" in sc.humanize("svn: E155004: sqlite busy"))
check("переклад чужого лока", "Somebody else has this file locked" in sc.humanize("svn: E195022: File locked"))
check("переклад логіна", "user name or password" in sc.humanize("svn: E170001: Authorization failed"))

# 12. scan_unprotected
need = sc.scan_unprotected(wc)
check("scan_unprotected не падає", isinstance(need, list), need)

# 13. апостроф U+02BC — його немає в ЖОДНОМУ ANSI-кодуванні.
#     Живий сервер показав: після звичайного svn delete файл зникає з диска
#     разом зі своїм 8.3-псевдонімом, і видалення стає неможливо здати взагалі.
APO = "звʼязок міста.blend"
open(os.path.join(wc, APO), "wb").write(b"B" * 200)
check("апостроф ʼ справді не кодується в ANSI",
      not sc._fits(APO, sc._acp()) and not sc._fits(APO, "cp1251"))
try:
    sc.add(wc, [APO])
    r = sc.commit(wc, [APO], "файл з апострофом")
    check("файл з апострофом здається", "commit" in r, r)
except Exception as e:
    check("файл з апострофом здається", False, e)

# людина стерла його в Провіднику -> статус missing, 8.3 більше немає
os.chmod(os.path.join(wc, APO), 0o666)
os.unlink(os.path.join(wc, APO))
check("8.3-псевдонім зник разом із файлом", sc._short(os.path.join(wc, APO)) is None)
try:
    sc.remove(wc, [APO])
    r = sc.commit(wc, [APO], "прибрав файл з апострофом")
    check("видалення файлу з апострофом здається", "commit" in r, r)
    sc.purge_deleted(wc, [APO])
    check("заглушку прибрано з диска", not os.path.exists(os.path.join(wc, APO)))
    check("з репозиторію прибрано", APO not in sc._dec(sc._run(["list", "."], cwd=wc)))
except Exception as e:
    check("видалення файлу з апострофом здається", False, e)

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 60)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 60)
sys.exit(1 if FAIL else 0)
