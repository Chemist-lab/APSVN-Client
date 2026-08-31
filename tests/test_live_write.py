# -*- coding: utf-8 -*-
"""Повний цикл на СПРАВЖНЬОМУ сервері: чекаут → лок → коміт → прибирання.

Пише в репозиторій, тому вмикається навмисне:

    set APSVN_LIVE_WRITE=1

Працює у тимчасовій робочій копії — та, що на диску в художника, не чіпається.
Після себе прибирає: доданий файл видаляється окремим комітом, у репозиторії
лишаються тільки записи в історії.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "vendor"))

import app
import svn_client as sc

if os.environ.get("APSVN_LIVE_WRITE") != "1":
    print("ПРОПУЩЕНО: цей набір пише в справжній репозиторій.")
    print("Щоб запустити: set APSVN_LIVE_WRITE=1")
    sys.exit(0)

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


a = app.Api()
url, u, p = a.c.get("url"), *a._creds()
if not url or not u:
    print("ПРОПУЩЕНО: немає збереженого підключення")
    sys.exit(0)

base = tempfile.mkdtemp(prefix="apsvn_lw_")
wc = os.path.join(base, "Тимчасова копія")     # кирилиця — і тут теж
NAME = "APSVN перевірка звʼязку.blend"
MSG = "APSVN: перевірка звʼязку — українські літери 🎬"

print("сервер:", url)
print("копія: ", wc)
print()

try:
    r = sc.checkout(url, wc, username=u, password=p)
    check("чекаут зі справжнього сервера", os.path.isdir(os.path.join(wc, ".svn")), r)

    with open(os.path.join(wc, NAME), "wb") as fh:
        fh.write(b"APSVN-LIVE-TEST" * 64)
    st = {f["path"]: f for f in sc.status(wc, me=u)}
    check("новий файл видно", st.get(NAME, {}).get("status") == "unversioned", st.get(NAME))

    sc.add(wc, [NAME])
    r = sc.commit(wc, [NAME], MSG, username=u, password=p)
    check("коміт на справжній сервер", "commit" in r, r)

    lg = sc.log(wc, limit=3, username=u, password=p)
    check("опис українською вцілів на сервері", lg and lg[0]["msg"] == MSG, lg[0]["msg"] if lg else None)
    check("автор — наш логін", lg and lg[0]["author"] == u, lg[0]["author"] if lg else None)

    # auto-props мав навісити needs-lock -> файл read-only, редагувати не можна
    ro = not os.access(os.path.join(wc, NAME), os.W_OK)
    check("файл захищено від правки без лока", ro)

    r = sc.lock(wc, [NAME], username=u, password=p)
    st = {f["path"]: f for f in sc.status(wc, remote=True, username=u, password=p, me=u)}
    check("лок на справжньому сервері мій", st.get(NAME, {}).get("lock_mine") is True, st.get(NAME))
    check("лок не вважається протухлим", st.get(NAME, {}).get("lock_stale") is False, st.get(NAME))

    with open(os.path.join(wc, NAME), "ab") as fh:
        fh.write(b"MORE")
    r = sc.commit(wc, [NAME], "APSVN: правка під локом", username=u, password=p)
    check("правка під локом здається", "commit" in r, r)

    st = {f["path"]: f for f in sc.status(wc, remote=True, username=u, password=p, me=u)}
    check("лок ПЕРЕЖИВ коміт (--no-unlock)", st.get(NAME, {}).get("lock_mine") is True, st.get(NAME))
    check("файл лишився доступним для запису", os.access(os.path.join(wc, NAME), os.W_OK))

    # --- історія і відкат просто на сервері ---------------------------------
    hist = sc.file_log(wc, NAME, username=u, password=p)
    check("історія файлу читається із сервера", len(hist) >= 2,
          [(h["rev"], h["action"]) for h in hist])
    check("описи в історії українською",
          any("перевірка звʼязку" in (h["msg"] or "") for h in hist),
          [h["msg"] for h in hist])
    first = hist[-1]["rev"]

    peek = os.path.join(base, "погляд.blend")
    sc.save_revision_as(wc, NAME, first, peek, username=u, password=p)
    check("стару версію вивантажено окремим файлом",
          os.path.getsize(peek) == 15 * 64, os.path.getsize(peek))
    check("бойовий файл при цьому не змінився",
          os.path.getsize(os.path.join(wc, NAME)) == 15 * 64 + 4)

    res = sc.restore_revision(wc, NAME, first, me=u, username=u, password=p,
                              rescue_dir=os.path.join(base, "запас"))
    check("відкат по мережі повернув точний розмір",
          os.path.getsize(os.path.join(wc, NAME)) == 15 * 64,
          os.path.getsize(os.path.join(wc, NAME)))
    check("запасну копію збережено", res["rescue"] and os.path.isfile(res["rescue"]))
    r = sc.commit(wc, [NAME], "APSVN: відкат до першої версії",
                  username=u, password=p)
    check("відкат здається на сервер", "commit" in r, r)

    sc.unlock(wc, [NAME], username=u, password=p)
    st = {f["path"]: f for f in sc.status(wc, remote=True, username=u, password=p, me=u)}
    check("після відпускання лока немає", not st.get(NAME, {}).get("lock_mine"), st.get(NAME))

    # --- повернення видаленого просто на сервері ----------------------------
    sc.remove(wc, [NAME])
    sc.commit(wc, [NAME], "APSVN: тимчасово прибрав", username=u, password=p)
    sc.purge_deleted(wc, [NAME])
    dead = [d for d in sc.deleted_files(wc, username=u, password=p)
            if d["path"] == NAME]
    check("сервер показує видалений файл", bool(dead), dead)
    if dead:
        sc.update(wc, username=u, password=p)
        sc.restore_deleted(wc, NAME, dead[0]["rev"], username=u, password=p)
        check("видалений файл повернувся з сервера",
              os.path.isfile(os.path.join(wc, NAME)))
        r = sc.commit(wc, [NAME], "APSVN: повернув видалений",
                      username=u, password=p)
        check("повернення здається на сервер", "commit" in r, r)
finally:
    # прибираємо за собою: файл видаляється з репозиторію
    try:
        sc.remove(wc, [NAME])
        r = sc.commit(wc, [NAME], "APSVN: прибрав файл перевірки", username=u, password=p)
        check("прибирання за собою", "commit" in r, r)
    except Exception as e:
        check("прибирання за собою", False, "ПРИБЕРИ ВРУЧНУ «%s»: %s" % (NAME, e))
    shutil.rmtree(base, ignore_errors=True)

print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
