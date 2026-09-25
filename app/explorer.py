# -*- coding: utf-8 -*-
"""Провідник проєкту: вміст однієї теки з усім, що про неї знає svn.

ТЕКА ЧИТАЄТЬСЯ БЕЗ МЕРЕЖІ. Раніше кожен клік по теці йшов на сервер
(`status -u -v --depth immediates` і ще два `svn info` для значка «нове
всередині»), і навігація була рівно такою швидкою, як мережа: «Reading
folder…», порожній список, миготіння. Тепер тека складається з трьох джерел:

  * диск (scandir) — що фізично лежить у теці, з розмірами й датами;
  * локальний `svn status --depth immediates` цієї теки — без -u, тобто без
    мережі: свої зміни, свої локи, нове, перенесене, конфлікти. Це те, що
    людина могла змінити секунду тому, тому питаємо щоразу — соті частки
    секунди;
  * ОСТАННЯ СИНХРОНІЗАЦІЯ (список, який state() тягне з сервера кожні 10 с):
    чужі локи, що нового на сервері, що ще не завантажено, «нове всередині».

Тобто сервер питається раз на синхронізацію для всього проєкту, а не на
кожен клік. Чуже з'являється в провіднику з тією ж затримкою, що й у списку
змін, — і це чесно: провідник показує проєкт станом на останню звірку.

Що видно із синхронізації (перевірено на двох робочих копіях і чужому локу):
  * чужий лок          -> repos-status/lock/owner, навіть якщо файл не змінено;
  * новіше на сервері  -> repos-status item="modified";
  * є на сервері, немає на диску -> wc-status "none" + repos-status "added".

«Нове всередині» для теки — будь-яка зміна з сервера під нею. Локи ревізій не
створюють, тож і значка не дають — це навмисно.
"""
import datetime
import os
import xml.etree.ElementTree as ET

import svn_client as sc

BROWSE_CAP = 3000

# Подвійний клік запускає файл у сторонній програмі. Це запуск чужого коду з
# мережевої шари, тому список ДОЗВОЛЕНИХ, а не заборонених. .lnk немає й не
# буде: імʼя ярлика нічого не каже про його ціль, а .exe/.bat/.ps1 у теці
# проєкту не мають запускатися ніколи.
OPENABLE = (".blend", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tga",
            ".psd", ".mov", ".mp4", ".mkv", ".wav", ".abc", ".fbx", ".obj",
            ".usd", ".usdc", ".txt", ".md", ".json", ".csv", ".pdf")


def inside(wc, rel):
    """Абсолютний шлях, який гарантовано лежить усередині робочої копії."""
    full = os.path.abspath(os.path.join(wc, (rel or "").replace("/", os.sep)))
    root = os.path.abspath(wc)
    a, b = os.path.normcase(full), os.path.normcase(root)
    if a != b and not a.startswith(b + os.sep):
        raise sc.SvnError("That path is outside the project.")
    return full


def _when(ts):
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _local_view(full):
    """Що svn знає про записи теки — ЛОКАЛЬНО, без мережі, за іменем.

    _retry=False навмисно: авто-cleanup у _run посеред чужої операції (іде
    оновлення, коміт) заважав би їй. Провідник — операція читання: не вийшло —
    мовчки обходимося останньою синхронізацією. None — теку svn не читає
    (наприклад, вона сама ще не під версійним контролем).
    """
    try:
        root = sc._xml(["status", ".", "--depth", "immediates"], cwd=full,
                       timeout=60, _retry=False)
    except (sc.SvnError, ET.ParseError, OSError):
        return None
    out = {}
    for tgt in root.findall("target"):
        for e in tgt.findall("entry"):
            raw = (e.get("path") or "").replace("\\", "/")
            if not raw or raw == ".":
                continue
            ws = e.find("wc-status")
            if ws is None:
                continue
            wl = ws.find("lock")
            conflicted = (ws.get("item") == "conflicted"
                          or ws.get("tree-conflicted") == "true"
                          or ws.get("props") == "conflicted")
            out[raw.split("/")[-1]] = {
                "status": "conflicted" if conflicted else ws.get("item"),
                "token": wl is not None,
                "owner": wl.findtext("owner") if wl is not None else None,
                "moved_from": sc._rel(ws.get("moved-from") or "") or None,
            }
    return out


# Стани, які означають «тут є твоя нездана робота».
LOCAL = ("modified", "added", "deleted", "missing", "unversioned",
         "replaced", "conflicted")


def browse(wc, rel="", username=None, password=None, remote=True, known=None,
           local=True):
    """Вміст ОДНІЄЇ теки: диск + локальний svn + остання синхронізація.

    known — список файлів з останнього state() (там чужі локи й те, що їде з
    сервера). Якщо його не дали, читаємо самі, з мережею, — так кличуть тести
    і так було раніше. local=False — не питати svn зовсім (іде передача: svn
    поруч зі svn на тій самій копії впирається в її замок).
    """
    rel = (rel or "").strip("/").replace("\\", "/")
    full = inside(wc, rel)
    if not os.path.isdir(full):
        raise sc.SvnError("That folder is no longer there.")
    if known is None:
        try:
            known = sc.status(wc, remote=remote, username=username,
                              password=password)
        except sc.SvnError:
            known = []
    kn = {k["path"]: k for k in known}
    here = _local_view(full) if local else None

    # Усередині невідомої svn теки невідоме все: svn status показує лише саму
    # теку одним рядком, а її вміст — ні.
    loose = any(rel == k["path"] or rel.startswith(k["path"] + "/")
                for k in known if k.get("status") == "unversioned")

    def lock_of(path, li):
        """(власник, мій, забраний). Свій токен видно локально й одразу —
        щойно взятий лок з'являється без синхронізації; чужий лок і «твій
        забрали» знає лише синхронізація."""
        ki = kn.get(path) or {}
        tok = (li["token"] if li is not None
               else bool(ki.get("lock_mine") or ki.get("lock_stale")))
        if tok:
            stale = bool(ki.get("lock_stale"))
            return ((li or {}).get("owner") or ki.get("lock_owner"),
                    not stale, stale)
        if ki.get("lock_owner") and not ki.get("lock_mine"):
            return ki["lock_owner"], False, False
        return None, False, False

    dirs, files, cut = [], [], False
    try:
        raw = sorted(os.scandir(full), key=lambda e: e.name.lower())
    except OSError:
        raise sc.SvnError("Could not read that folder.")

    for e in raw:
        if e.name == ".svn" or sc.JUNK_RE.search(e.name):
            continue
        try:
            is_dir = e.is_dir(follow_symlinks=False)
            # переходи й посилання не розкриваємо: вони розмножують вміст
            link = e.is_symlink() or (is_dir and e.is_junction()
                                      if hasattr(e, "is_junction") else False)
            stt = e.stat(follow_symlinks=False)
        except OSError:
            continue
        path = (rel + "/" + e.name) if rel else e.name
        li = here.get(e.name) if here is not None else None
        ki = kn.get(path) or {}
        if loose:
            st = "unversioned"
        elif li is not None:
            st = li["status"]
        elif here is not None:
            st = "normal"            # svn про запис змовчав — отже, нічого нового
        else:
            st = ki.get("status") or "normal"
        owner, mine, stale = lock_of(path, li)
        low = e.name.lower()
        moved_from = (li or {}).get("moved_from") or ki.get("moved_from")
        row = {
            "name": e.name, "path": path,
            "kind": "dir" if is_dir else "file",
            "size": None if is_dir else stt.st_size,
            "mtime": _when(stt.st_mtime), "link": bool(link), "on_disk": True,
            "status": st,
            "status_text": ("moved here" if moved_from and st == "added"
                            else sc.STATUS_TEXT.get(st, st)),
            "remote_change": bool(ki.get("remote_change")),
            "lock_owner": owner, "lock_mine": mine, "lock_stale": stale,
            "moved_from": moved_from,
            "binary": low.endswith(sc.BINARY_EXT),
            "openable": low.endswith(OPENABLE),
            "nested": is_dir and os.path.isdir(os.path.join(e.path, ".svn")),
        }
        (dirs if is_dir else files).append(row)
        if len(dirs) + len(files) >= BROWSE_CAP:
            cut = True
            break

    # Є на сервері, але ще не завантажене. Без цього рядка людина такий файл
    # не побачить узагалі й вважатиме, що його немає. Видалене й перенесене
    # звідси НЕ показуємо: на диску його вже немає, а в «Changes» воно є.
    shown = {r["name"] for r in dirs + files}
    for k in known:
        parent, _, name = k["path"].rpartition("/")
        if parent != rel or not name or name in shown:
            continue
        if k.get("status") == "none" and k.get("remote_change"):
            files.append({
                "name": name, "path": k["path"], "kind": "file", "size": None,
                "mtime": "", "link": False, "on_disk": False, "status": "none",
                "status_text": "not downloaded yet", "remote_change": True,
                "lock_owner": k.get("lock_owner"),
                "lock_mine": bool(k.get("lock_mine")),
                "lock_stale": bool(k.get("lock_stale")),
                "moved_from": None,
                "binary": name.lower().endswith(sc.BINARY_EXT),
                "openable": False, "nested": False,
            })

    # «Нове всередині» і «твоя нездана робота всередині» — з уже відомого
    # списку, без жодного запиту.
    for d in dirs:
        pre = d["path"] + "/"
        d["new_inside"] = any(k.get("remote_change") and k["path"].startswith(pre)
                              for k in known)
        d["mine_inside"] = any(k.get("status") in LOCAL and k["path"].startswith(pre)
                               for k in known)

    return {"path": rel,
            "parent": (rel.rsplit("/", 1)[0] if "/" in rel
                       else (None if not rel else "")),
            "entries": dirs + files, "truncated": cut}


def details(wc, rel):
    """Подробиці одного файлу для панелі перегляду."""
    full = inside(wc, rel)
    if not os.path.isfile(full):
        raise sc.SvnError("That file is no longer there.")
    stt = os.stat(full)
    out = {"path": rel, "name": os.path.basename(rel), "size": stt.st_size,
           "mtime": _when(stt.st_mtime),
           "writable": os.access(full, os.W_OK), "preview": None,
           "preview_w": None, "preview_h": None}
    low = rel.lower()
    try:
        if low.endswith(".blend"):
            import blendthumb
            got = blendthumb.blend_thumbnail(full)
            if got:
                import base64
                w, h, png = got
                out["preview"] = "data:image/png;base64," + \
                    base64.b64encode(png).decode("ascii")
                out["preview_w"], out["preview_h"] = w, h
        else:
            import imgthumb
            out["preview"] = imgthumb.preview_data_uri(full)
    except Exception:
        out["preview"] = None      # превʼю ніколи не має валити провідник
    return out
