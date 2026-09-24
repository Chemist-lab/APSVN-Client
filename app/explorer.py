# -*- coding: utf-8 -*-
"""Провідник проєкту: вміст однієї теки з усім, що про неї знає svn.

Дані беремо ЛІНИВО, по одній теці. Заміри на копії з 2000 файлів:
`status -u -v --depth immediates` на ОДНУ теку — 24 КБ і 0.045 с, тоді як на
все дерево — 505 КБ і 0.072 с. За часом різниця мала, за обсягом — у 21 раз,
а розбирати півмегабайта XML щоразу, коли людина клікнула теку, немає сенсу.

Що звідти видно (перевірено на двох робочих копіях і чужому локу):
  * чужий лок          -> repos-status/lock/owner, навіть якщо файл не змінено;
  * власний лок        -> wc-status/lock, видно й без мережі;
  * новіше на сервері  -> repos-status item="modified";
  * є на сервері, немає на диску -> wc-status "none" + repos-status "added";
  * відсутній <repos-status> у режимі -v означає «і лока немає, і новин немає».

Чого звідти дістати НЕ можна — значка «всередині цієї теки щось нове». Його
доводиться рахувати окремо, бо last-changed ревізія теки в svn підіймається
з піддерева, а локи — ні (вони не створюють ревізій).
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


def _dir_revisions(cwd, username, password):
    """Ревізії підтек: та, що в нас, і та, що на сервері."""
    def grab(args):
        out = {}
        try:
            root = sc._xml(args, cwd=cwd, username=username, password=password,
                           timeout=120, _retry=False)
        except (sc.SvnError, ET.ParseError):
            return out
        for e in root.findall("entry"):
            p = (e.get("path") or "").replace("\\", "/")
            c = e.find("commit")
            if p and p != "." and c is not None:
                out[p.split("/")[-1]] = c.get("revision")
        return out

    here = grab(["info", ".", "--depth", "immediates"])
    head = grab(["info", ".", "-r", "HEAD", "--depth", "immediates"])
    return here, head


def _svn_view(full, remote, username, password):
    """Стан кожного запису теки очима svn, за іменем."""
    by_name = {}
    args = ["status", ".", "-v", "--depth", "immediates"]
    if remote:
        args.insert(2, "-u")
    try:
        # _retry=False навмисно: авто-cleanup у _run під час чужого коміту
        # заважав би йому. Провідник — операція читання, він мовчки відступає.
        root = sc._xml(args, cwd=full, timeout=None if remote else 120,
                       username=username if remote else None,
                       password=password if remote else None, _retry=False)
    except (sc.SvnError, ET.ParseError):
        return by_name             # неверсіонована тека — це не збій
    for tgt in root.findall("target"):
        for e in tgt.findall("entry"):
            raw = (e.get("path") or "").replace("\\", "/")
            if not raw or raw == ".":
                continue
            name = raw.split("/")[-1]
            ws, rs = e.find("wc-status"), e.find("repos-status")
            wl = ws.find("lock") if ws is not None else None
            rl = rs.find("lock") if rs is not None else None
            if remote:
                owner = rl.findtext("owner") if rl is not None else None
                same = (rl is not None and wl is not None and
                        rl.findtext("token") == wl.findtext("token"))
                mine, stale = bool(same), bool(wl is not None and not same)
            else:
                owner = wl.findtext("owner") if wl is not None else None
                mine, stale = wl is not None, False
            by_name[name] = {
                "status": ws.get("item") if ws is not None else "none",
                "remote_change": bool(rs is not None and
                                      rs.get("item") not in (None, "none")),
                "lock_owner": owner, "lock_mine": mine, "lock_stale": stale,
            }
    return by_name


def browse(wc, rel="", username=None, password=None, remote=True):
    """Вміст ОДНІЄЇ теки: усе, що є на диску, плюс те, що знає про неї svn."""
    rel = (rel or "").strip("/").replace("\\", "/")
    full = inside(wc, rel)
    if not os.path.isdir(full):
        raise sc.SvnError("That folder is no longer there.")

    seen = _svn_view(full, remote, username, password)
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
        low = e.name.lower()
        si = seen.pop(e.name, {})
        st = si.get("status", "unversioned")
        row = {
            "name": e.name,
            "path": (rel + "/" + e.name) if rel else e.name,
            "kind": "dir" if is_dir else "file",
            "size": None if is_dir else stt.st_size,
            "mtime": _when(stt.st_mtime), "link": bool(link), "on_disk": True,
            "status": st, "status_text": sc.STATUS_TEXT.get(st, st),
            "remote_change": si.get("remote_change", False),
            "lock_owner": si.get("lock_owner"),
            "lock_mine": si.get("lock_mine", False),
            "lock_stale": si.get("lock_stale", False),
            "binary": low.endswith(sc.BINARY_EXT),
            "openable": low.endswith(OPENABLE),
            "nested": is_dir and os.path.isdir(os.path.join(e.path, ".svn")),
        }
        (dirs if is_dir else files).append(row)
        if len(dirs) + len(files) >= BROWSE_CAP:
            cut = True
            break

    # Є на сервері, але ще не завантажене. Без цього рядка людина такий файл
    # не побачить узагалі й вважатиме, що його немає.
    for name, si in seen.items():
        if si.get("status") in ("none", "deleted") or si.get("remote_change"):
            files.append({
                "name": name, "path": (rel + "/" + name) if rel else name,
                "kind": "file", "size": None, "mtime": "", "link": False,
                "on_disk": False, "status": si.get("status", "none"),
                "status_text": "not downloaded yet", "remote_change": True,
                "lock_owner": si.get("lock_owner"),
                "lock_mine": si.get("lock_mine", False),
                "lock_stale": si.get("lock_stale", False),
                "binary": name.lower().endswith(sc.BINARY_EXT),
                "openable": False, "nested": False,
            })

    if dirs and remote:
        here, head = _dir_revisions(full, username, password)
        for d in dirs:
            a, b = here.get(d["name"]), head.get(d["name"])
            d["new_inside"] = bool(a and b and a != b)

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
