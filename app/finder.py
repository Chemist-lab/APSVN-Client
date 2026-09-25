# -*- coding: utf-8 -*-
"""Пошук: файли й теки проєкту (провідник) і коміти історії.

Одне правило на обидва: слова через пробіл, кожне мусить знайтися, регістр
не важить (кирилиця теж). Файл шукається за шляхом, але хоч одне слово має
стояти в імені самого файлу чи теки: інакше «new_w» знайшов би, крім теки
ассета й new_w.blend, ще й кожну текстуру в цій теці — шлях до неї теж
містить «new_w». А «new_w png» — якраз картинки цієї теки.

Файли шукаються на диску, без svn і без мережі: обхід теки проєкту — частки
секунди, а `svn list -R` чи `svn status` по всьому проєкту — мережа або
секунди на великій копії. Що про файл знає svn (змінено, чий лок, новіше на
сервері, ще не завантажено), береться з останньої синхронізації — так само,
як у провіднику (див. шапку explorer.py).
"""
import os

import explorer as ex
import svn_client as sc

FILES_CAP = 300          # скільки знайденого показати за раз
INDEX_CAP = 150000       # скільки записів проєкту обходити взагалі
COMMITS_CAP = 300


def words(query):
    """Слова пошуку: без регістру; зворотна скісна — як пряма (шлях із Windows)."""
    return [w for w in str(query or "").casefold().replace("\\", "/").split() if w]


def index(wc, cap=INDEX_CAP):
    """Усе, що лежить у копії, одним списком. -> (записи, обрізано?)

    Запис — (шлях від кореня копії, тека?, розмір, mtime, ярлик?, вкладений?).
    .svn, сміття системи й Blender, ярлики й переходи (junction) — як у
    browse(): переходи розмножували б вміст. Вкладений окремий проєкт видно,
    але всередину не заходимо — він не наш.
    """
    out, stack = [], [("", os.path.abspath(wc))]
    while stack:
        rel, full = stack.pop()
        try:
            it = os.scandir(full)
        except OSError:
            continue
        with it:
            for e in it:
                if e.name == ".svn" or sc.JUNK_RE.search(e.name):
                    continue
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                    link = e.is_symlink() or (is_dir and e.is_junction()
                                              if hasattr(e, "is_junction") else False)
                    stt = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                path = (rel + "/" + e.name) if rel else e.name
                nested = bool(is_dir and not link and
                              os.path.isdir(os.path.join(e.path, ".svn")))
                out.append((path, is_dir, None if is_dir else stt.st_size,
                            stt.st_mtime, bool(link), nested))
                if len(out) >= cap:
                    return out, True
                if is_dir and not link and not nested:
                    stack.append((path, e.path))
    return out, False


def _fits(path, ws):
    low = path.casefold()
    name = low.rsplit("/", 1)[-1]
    return all(w in low for w in ws) and any(w in name for w in ws)


def _rank(row, ws):
    """Спершу точна назва (з розширенням чи без), далі ті, що з неї починаються,
    решта — потім; теки перед файлами, ближчі до кореня — вище."""
    name = row["name"].casefold()
    whole = " ".join(ws)
    if name == whole or name.rsplit(".", 1)[0] == whole:
        first = 0
    elif any(name.startswith(w) for w in ws):
        first = 1
    else:
        first = 2
    return (first, row["kind"] != "dir", row["path"].count("/"),
            row["path"].casefold())


def files(query, idx, known, cap=FILES_CAP):
    """Знайдене в проєкті: рядки того ж вигляду, що й у browse(), плюс where —
    тека, де воно лежить (у списку знайденого без неї не зрозуміти, котрий із
    двох однойменних файлів котрий)."""
    ws = words(query)
    if not ws:
        return {"entries": [], "total": 0}
    kn = {k["path"]: k for k in known}
    loose = [k["path"] for k in known if k.get("status") == "unversioned"]
    rows, seen = [], set()
    for path, is_dir, size, mtime, link, nested in idx:
        if not _fits(path, ws):
            continue
        seen.add(path)
        ki = kn.get(path) or {}
        if any(path == p or path.startswith(p + "/") for p in loose):
            st = "unversioned"             # у кинутій теці невідоме все
        else:
            st = ki.get("status") or "normal"
        name = path.rsplit("/", 1)[-1]
        low = name.lower()
        moved_from = ki.get("moved_from")
        rows.append({
            "name": name, "path": path, "where": path.rpartition("/")[0],
            "kind": "dir" if is_dir else "file", "size": size,
            "mtime": ex._when(mtime), "link": link, "on_disk": True,
            "status": st,
            "status_text": ("moved here" if moved_from and st == "added"
                            else sc.STATUS_TEXT.get(st, st)),
            "remote_change": bool(ki.get("remote_change")),
            "lock_owner": ki.get("lock_owner"),
            "lock_mine": bool(ki.get("lock_mine")),
            "lock_stale": bool(ki.get("lock_stale")),
            "moved_from": moved_from,
            "binary": low.endswith(sc.BINARY_EXT),
            "openable": low.endswith(ex.OPENABLE),
            "nested": nested,
        })
    # Є на сервері, але ще не завантажене — як у browse(): без цього рядка
    # людина вирішила б, що такого файлу немає зовсім.
    for k in known:
        path = k.get("path") or ""
        if not (k.get("status") == "none" and k.get("remote_change")) \
                or path in seen or not _fits(path, ws):
            continue
        name = path.rsplit("/", 1)[-1]
        rows.append({
            "name": name, "path": path, "where": path.rpartition("/")[0],
            "kind": "file", "size": None, "mtime": "", "link": False,
            "on_disk": False, "status": "none",
            "status_text": "not downloaded yet", "remote_change": True,
            "lock_owner": k.get("lock_owner"),
            "lock_mine": bool(k.get("lock_mine")),
            "lock_stale": bool(k.get("lock_stale")),
            "moved_from": None,
            "binary": name.lower().endswith(sc.BINARY_EXT),
            "openable": False, "nested": False,
        })
    rows.sort(key=lambda r: _rank(r, ws))
    return {"entries": rows[:cap], "total": len(rows)}


def commits(query, entries, cap=COMMITS_CAP):
    """Коміти, де кожне слово є в описі, в імені автора або в шляху зміненого.

    hits — які саме файли коміту підійшли (до трьох), щоб у списку було
    видно, ЧОМУ коміт знайшовся: опис «правки» нічого не каже, а
    «Assets/Character/new_w/new_w.blend» — каже.
    """
    ws = words(query)
    if not ws:
        return {"rows": [], "total": 0}
    out = []
    for e in entries:
        text = ((e.get("msg") or "") + "\n" + (e.get("author") or "")).casefold()
        paths = e.get("paths") or []
        low = [p.casefold() for p in paths]
        if not all(w in text or any(w in p for p in low) for w in ws):
            continue
        hits = [paths[i] for i, p in enumerate(low) if any(w in p for w in ws)]
        out.append({"rev": e.get("rev"), "author": e.get("author"),
                    "date": e.get("date"), "msg": e.get("msg"),
                    "hits": hits[:3], "nhits": len(hits)})
    return {"rows": out[:cap], "total": len(out)}
