# -*- coding: utf-8 -*-
"""APSVN — простий SVN-клієнт для художників (стиль Diversion).

Запуск: APSVN.bat (без консолі) або python app.py.

Рішення за результатами аудиту:
* жодного трейсбека в обличчя художнику — усі помилки або перекладені
  людською мовою в svn_client.humanize(), або лягають у error.log і
  показуються віконцем;
* state() ніколи не блокується за довгою операцією — повертає останній
  відомий стан із прапорцем busy, тож інтерфейс не «замерзає» на коміті;
* коміт бінарника без свого лока відхиляється до передачі гігабайтів —
  інакше людина чекала б годину, щоб отримати 423 Locked;
* закриття вікна під час передачі блокується.

Мультипроєктність:
* config.json тримає список проєктів І ДЗЕРКАЛО поточного у старих плоских
  ключах. Це не надмірність: README радить копіювати теку APSVN, тож на
  студії неминуче лежатимуть дві збірки на один %APPDATA%. Стара, не знаючи
  про "projects", працювала б з поточним проєктом і, перезаписавши документ,
  знищила б увесь список. З дзеркалом вона псує лише дзеркало;
* пароль у сховищі Windows ключується ПРОЄКТОМ, а не логіном: два проєкти з
  однаковим логіном і різними паролями інакше затирали б один одного, а
  повторні спроби з чужим паролем ще й блокували б обліковку на сервері;
* зламаний окремий проєкт (відпав мережевий диск) НЕ кидає людину в майстер
  підключення — інакше єдиною видимою кнопкою лишається «Підключити», і
  повернутися в робочий проєкт неможливо.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback

# залежності вендоряться в ./vendor — застосунок самодостатній, жодних
# pip install у художників. Теку застосунку додаємо явно, бо запуск із
# хвостовим "\" у шляху ламає стандартний sys.path[0].
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.join(APP_DIR, "vendor"))

CONF_DIR = os.path.join(os.environ.get("APPDATA", "."), "APSVN")
CONF = os.path.join(CONF_DIR, "config.json")
LOG = os.path.join(CONF_DIR, "error.log")
RESCUE = os.path.join(CONF_DIR, "rescue")
# Номер версії — єдине місце на весь проєкт. Збірка бере його звідси,
# і оновлення порівнюватиме його з тим, що лежить на сервері.
VERSION = "1.0.0"

KEYRING_SERVICE = "APSVN"
FORMAT = 2


def fatal(title, text, exc=None):
    """Показати причину людині, а не мовчки померти під pythonw."""
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("\n=== %s ===\n%s\n" % (title, exc or text))
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "%s\n\nDetails: %s" % (text, LOG), "APSVN — " + title, 0x10)
    except Exception:
        print(title, text, file=sys.stderr)
    sys.exit(1)


try:
    import keyring
    import webview
    import svn_client as sc
    import explorer as ex
    import shellicon as si
except Exception:
    fatal("could not start",
          "Some parts of the application are missing. Most likely APSVN was "
          "copied without its vendor folder, or a different Python is "
          "installed.", traceback.format_exc())


_BROKEN_CODES = ("E155007", "E155036", "E155000")


def is_broken(e):
    """Чи означає помилка «проєкт зламаний», а не «щось не вийшло».

    За кодом, а не за українським підрядком: текст перекладу змінюється, і
    крихкий пошук по ньому тихо перестав би працювати.
    """
    raw = getattr(e, "raw", "") or ""
    return any(code in raw for code in _BROKEN_CODES)


def _mmss(sec):
    sec = int(round(sec))
    return "%ds" % sec if sec < 60 else "%dm %02ds" % (sec // 60, sec % 60)


def _bullets(items, cap=8):
    """Список для повідомлення — з обрізанням, щоб вікно не поїхало."""
    shown = ["  • " + str(i) for i in items[:cap]]
    if len(items) > cap:
        shown.append("  … and %d more" % (len(items) - cap))
    return "\n".join(shown)


def project_id(url, wc):
    """Стабільний id: повторне підключення того самого проєкту не плодить
    записів і не губить збережений пароль."""
    key = (url or "").rstrip("/") + "|" + os.path.normcase(os.path.abspath(wc or ""))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _blank():
    return {"format": FORMAT, "projects": [], "current": None}


def load_conf():
    """Прочитати конфіг, розрізняючи «немає» і «побився»."""
    for path in (CONF, CONF + ".bak"):
        try:
            with open(path, encoding="utf-8") as fh:
                c = json.load(fh)
        except FileNotFoundError:
            continue
        except Exception:
            # побитий файл не викидаємо: з нього ще можна витягти проєкти
            try:
                os.replace(path, path + ".broken-" + time.strftime("%Y%m%d-%H%M%S"))
            except OSError:
                pass
            continue
        if not isinstance(c, dict):
            continue
        return migrate(c)
    return _blank()


def migrate(c):
    """Старий плоский конфіг -> список проєктів. Ідемпотентно."""
    if isinstance(c.get("projects"), list) and c["projects"]:
        c.setdefault("format", FORMAT)
        ids = [p.get("id") for p in c["projects"]]
        if c.get("current") not in ids:
            c["current"] = ids[0] if ids else None
        return c
    if c.get("wc") and c.get("url"):
        pid = project_id(c["url"], c["wc"])
        return {"format": FORMAT, "current": pid, "projects": [{
            "id": pid, "name": c.get("name") or
            c["url"].rstrip("/").split("/")[-1],
            "wc": c["wc"], "url": c["url"],
            "username": c.get("username") or "",
        }]}
    return _blank()


def save_conf(c, dropped=None):
    """Атомарно, з fsync і резервною копією.

    Без fsync перейменування на NTFS фіксується раніше за дані: після зникнення
    живлення лишався б config.json нульової довжини. Раніше ціною була одна
    тека, тепер — увесь список проєктів.

    dropped — id, які щойно прибрали. Без цього злиття з диском воскрешало б
    їх назад, і кнопка «Прибрати зі списку» тихо нічого не робила.
    """
    os.makedirs(CONF_DIR, exist_ok=True)
    # інше вікно APSVN могло додати проєкт, поки ми думали — не затираємо його
    try:
        with open(CONF, encoding="utf-8") as fh:
            disk = json.load(fh)
        known = {p["id"] for p in c.get("projects", [])} | set(dropped or ())
        for p in disk.get("projects", []):
            if isinstance(p, dict) and p.get("id") and p["id"] not in known:
                c["projects"].append(p)
    except Exception:
        pass

    cur = next((p for p in c.get("projects", []) if p["id"] == c.get("current")),
               None)
    doc = dict(c)
    doc["format"] = FORMAT
    # дзеркало для старих збірок APSVN на цій же машині
    for k in ("wc", "url", "username", "name"):
        doc[k] = (cur or {}).get(k)

    try:
        if os.path.isfile(CONF):
            shutil.copyfile(CONF, CONF + ".bak")
    except OSError:
        pass
    tmp = CONF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, CONF)


class Api:
    def __init__(self):
        self.conf = load_conf()
        self._lock = threading.Lock()
        self.busy = threading.Event()      # триває довга операція
        self._prog = None                  # поступ поточної передачі
        self._last = {}                    # кеш стану ПО ПРОЄКТАХ
        sc.ensure_config(CONF_DIR)

    # --- проєкти ---
    @property
    def projects(self):
        return self.conf.get("projects", [])

    def _proj(self, pid=None):
        pid = pid or self.conf.get("current")
        for p in self.projects:
            if p["id"] == pid:
                return p
        return self.projects[0] if self.projects else None

    @property
    def c(self):
        """Поточний проєкт. Назва збережена заради сумісності з тестами."""
        return self._proj() or {}

    def _creds(self, p=None):
        p = p or self._proj()
        if not p:
            return None, None
        u = p.get("username")
        pw = None
        for key in ("proj:" + p["id"], u):
            if not key:
                continue
            try:
                pw = keyring.get_password(KEYRING_SERVICE, key)
            except Exception:
                pw = None
            if pw:
                break            # старий ключ лишаємо як запасний назавжди
        return u, pw

    def _wc(self):
        p = self._proj()
        if not p or not p.get("wc") or not os.path.isdir(p["wc"]):
            raise sc.SvnError("The project folder is not available right now.")
        return p["wc"]

    def _guard(self, fn, *a, **kw):
        """Довга операція: один одночасно, з прапорцем зайнятості."""
        if not self._lock.acquire(blocking=False):
            raise sc.SvnError("Please wait — the previous action is still running.")
        self.busy.set()
        self._prog = None
        try:
            return fn(*a, **kw)
        finally:
            self._prog = None
            self.busy.clear()
            self._lock.release()

    def progress(self):
        """Поступ передачі. НЕ бере замок — інакше поки йде передача, ми не
        могли б про неї нічого розповісти."""
        return self._prog

    # --- дрібні налаштування інтерфейсу ---
    def set_pref(self, key, value):
        """«Більше не питати» і подібне.

        Зберігаємо в config.json, а не в localStorage вебвʼю: pywebview щоразу
        піднімає свій сервер на НОВОМУ порту, тож сховище браузера прив'язане
        до порту й помирає разом із ним.
        """
        self.conf.setdefault("prefs", {})[str(key)] = bool(value)
        save_conf(self.conf)
        return True

    def prefs(self):
        return self.conf.get("prefs", {})

    def icons(self, exts):
        """Іконки типів файлів — беремо з Windows, а не возимо з собою.

        Інтерфейс сам каже, які розширення йому трапились: перелічувати їх тут
        наперед означало б або тягнути іконки, яких ніхто не побачить, або
        забути чиєсь розширення. Порожня відповідь на розширення — нормально,
        інтерфейс лишає свій значок.
        """
        try:
            return si.icons(exts)
        except Exception:
            return {}

    def _rate(self, kind):
        """Швидкість, ЗАМІРЯНА на попередніх передачах, байтів за секунду.

        Саме заміряна, а не вирахувана: замір показав, що лічильники читань
        дають 1.0-2.0x обсягу залежно від того, один це великий файл чи сотня
        дрібних, тож із них оцінки не зробиш. А ось «скільки байтів за скільки
        секунд насправді поїхало минулого разу» — число чесне, і воно саме
        підлаштовується під мережу конкретної людини.
        """
        try:
            v = float(self.conf.get("rates", {}).get(kind) or 0)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    def _learn_rate(self, kind, nbytes, seconds):
        if not nbytes or nbytes < 4 * 1024 * 1024 or seconds < 1.0:
            return                      # надто дрібно, щоб щось із того вчити
        r = nbytes / seconds
        old = self._rate(kind)
        # ковзне середнє: одна аномально повільна здача не псує оцінку надовго
        self.conf.setdefault("rates", {})[kind] = r if old is None             else old * 0.6 + r * 0.4
        try:
            save_conf(self.conf)
        except Exception:
            pass

    def _tick(self, e):
        self._prog = e

    def _brief(self):
        return [{"id": p["id"], "name": p.get("name") or "project",
                 "wc": p.get("wc"), "url": p.get("url")} for p in self.projects]

    # --- стан ---
    def state(self, remote=False):
        """Ніколи не блокується: якщо йде довга дія — віддає попередній стан."""
        p = self._proj()
        if not p:
            return {"configured": False, "projects": []}
        pid = p["id"]
        base = {"configured": True, "pid": pid, "projects": self._brief(),
                "current": pid, "name": p.get("name") or "project",
                "wc": p.get("wc"), "me": p.get("username"),
                "version": VERSION,
                "prefs": self.conf.get("prefs", {})}

        if not self._lock.acquire(blocking=False):
            out = dict(self._last.get(pid) or base)
            out["busy"] = True
            return out
        try:
            if not p.get("wc") or not os.path.isdir(p["wc"]):
                # НЕ майстер: інакше з випадайкою зникає єдиний шлях назад
                return dict(base, broken="The project folder is not available. "
                                         "Maybe a drive is not connected.",
                            files=[], busy=False)
            u, pw = self._creds(p)
            try:
                info = sc.info(p["wc"])
            except sc.SvnError as e:
                if is_broken(e):
                    return dict(base, broken=str(e), files=[], busy=False)
                return dict(self._last.get(pid) or base, warn=str(e))
            meta = {}
            moved = None
            try:
                files = sc.status(p["wc"], remote=bool(remote), username=u,
                                  password=pw, me=u, meta=meta)
                warn = None
            except sc.SvnError as e:
                files = (self._last.get(pid) or {}).get("files", [])
                warn = str(e)
                # сервер переїхав: адресу пропонує ВІН, тож лише показуємо її
                # людині, а переводити копію будемо тільки на її дозвіл
                moved = sc.moved_to(e)
            # ЧОМУ НЕ РІЗНИЦЯ РЕВІЗІЙ. Раніше тут стояло HEAD мінус ревізія
            # копії — і одразу після ВЛАСНОЇ здачі людині писало «відстаєш на
            # 1», хоч у неї було все. Причина: svn піднімає ревізію лише зданих
            # шляхів, а не всієї копії, тож її корінь лишається на старому
            # числі. Рахуємо не ревізії, а справжні вхідні зміни — те, що
            # реально приїде під час «Get latest».
            incoming = [{"path": f["path"],
                         "kind": f.get("remote_kind") or "modified"}
                        for f in files if f.get("remote_change")]
            self._last[pid] = dict(base, busy=False, warn=warn, info=info,
                                   files=files, head=meta.get("head"),
                                   incoming=incoming[:300],
                                   incoming_n=len(incoming),
                                   broken=None, moved_to=moved)
            return self._last[pid]
        finally:
            self._lock.release()

    def switch_project(self, pid):
        if self.busy.is_set():
            raise sc.SvnError(
                "Please wait — project “%s” is still talking to the "
                "server." % (self.c.get("name") or "current"))
        if not any(p["id"] == pid for p in self.projects):
            raise sc.SvnError("That project is no longer in the list.")
        self.conf["current"] = pid
        save_conf(self.conf)
        return True

    def forget_project(self, pid):
        """Прибрати зі списку. Файли на диску не чіпаємо."""
        if self.busy.is_set():
            raise sc.SvnError("Please wait — still talking to the server.")
        p = self._proj(pid)
        if not p:
            return True
        held = []
        try:
            u, _ = self._creds(p)
            if p.get("wc") and os.path.isdir(p["wc"]):
                held = [f["path"] for f in sc.status(p["wc"], me=u)
                        if f.get("lock_mine")]
        except sc.SvnError:
            pass
        self.conf["projects"] = [x for x in self.projects if x["id"] != pid]
        if self.conf.get("current") == pid:
            self.conf["current"] = (self.projects[0]["id"]
                                    if self.projects else None)
        self._last.pop(pid, None)
        save_conf(self.conf, dropped={pid})
        if held:
            return ("Project removed from the list. WARNING: %d file(s) are "
                    "still locked by you — nobody else can edit them until you "
                    "connect to this project again and release them."
                    % len(held))
        return "Project removed from the list. The files on disk are untouched."

    def set_password(self, password, pid=None):
        """Переввести пароль, не запускаючи повторне підключення."""
        p = self._proj(pid)
        if not p:
            raise sc.SvnError("There is no project")
        return self._store_password(p, password)

    def _store_password(self, p, password):
        key = "proj:" + p["id"]
        try:
            keyring.set_password(KEYRING_SERVICE, key, password or "")
            if keyring.get_password(KEYRING_SERVICE, key) != (password or ""):
                raise RuntimeError("not stored")
            return True
        except Exception:
            # мовчати не можна: людина днями не знатиме, що пароль не лягає
            raise sc.SvnError(
                "The password could not be saved in Windows. APSVN will still "
                "work, but you will have to type the password again after a "
                "restart.")

    # --- підключення ---
    def probe(self, folder, url):
        """Що вже лежить у теці — ДО того, як щось качати."""
        st = sc.probe_dir(folder or "")
        if st["state"] == "subdir":
            raise sc.SvnError(
                "This folder is inside another project (%s). Pick a folder "
                "outside it — nested projects break the file list."
                % st.get("wcroot"))
        if st["state"] == "wc":
            have = (st.get("url") or "").rstrip("/")
            if have and have != (url or "").rstrip("/"):
                raise sc.SvnError(
                    "This folder already holds a different project:\n%s\n"
                    "Pick an empty folder, or point at that project instead."
                    % have)
        return st

    def add_project(self, url, folder, username, password, name=None):
        url, folder = (url or "").strip().rstrip("/"), (folder or "").strip()
        username = (username or "").strip()
        if not url or not folder or not username:
            raise sc.SvnError("Fill in the address, the folder and the user name")
        os.makedirs(folder, exist_ok=True)
        st = self.probe(folder, url)          # перевірка ДО збереження

        pid = project_id(url, folder)
        rec = {"id": pid, "name": (name or "").strip() or
               url.rstrip("/").split("/")[-1],
               "wc": folder, "url": url, "username": username}
        self.conf["projects"] = [x for x in self.projects if x["id"] != pid]
        self.conf["projects"].append(rec)
        self.conf["current"] = pid
        # запамʼятовуємо ДО завантаження: обірваний перший чекаут потім
        # продовжиться, а не почнеться з нуля
        save_conf(self.conf)
        self._store_password(rec, password)

        def work():
            if st["state"] in ("wc", "broken"):
                try:
                    sc.cleanup(folder)
                except sc.SvnError:
                    pass
                sc.update(folder, username=username, password=password,
                          progress=self._tick)
            else:
                sc.checkout(url, folder, username=username, password=password,
                            progress=self._tick)
            # разово захищаємо вже наявні бінарники (нові захистить auto-props)
            try:
                need = sc.scan_unprotected(folder)
                if need:
                    sc.set_needs_lock(folder, need)
                    sc.commit(folder, need,
                              "APSVN: protect files from simultaneous editing",
                              username=username, password=password)
            except sc.SvnError:
                pass
            return True

        return self._guard(work)

    # стара назва — щоб не ламати наявні виклики й тести
    setup = add_project

    # --- дії ---
    def do_update(self):
        u, p = self._creds()
        last = self._last.get(self.c.get("id")) or {}
        total = last.get("incoming_n") or None
        return self._guard(sc.update, self._wc(), username=u, password=p,
                           progress=self._tick, total=total)

    def do_commit(self, paths, message, keep_locks=None):
        wc, (u, p) = self._wc(), self._creds()
        message = (message or "").strip()
        if not message:
            raise sc.SvnError("Write a short note about what you did")

        def work():
            st = {f["path"]: f for f in sc.status(wc, me=u)}
            # Збираємо ВСІ перепони одразу, а не падаємо на першій. З появою
            # «виділити все» людина позначає сорок файлів, і відмова по одному
            # перетворилася б на сорок заходів.
            junk, taken, unlocked = [], [], []
            for x in paths:
                if sc.JUNK_RE.search(os.path.basename(x)):
                    junk.append(x)
                    continue
                f = st.get(x, {})
                # бінарник без свого лока: краще відмовити зараз, ніж лити
                # гігабайти й отримати відмову сервера наприкінці
                if f.get("status") == "modified" and f.get("binary") \
                        and not f.get("lock_mine"):
                    who = f.get("lock_owner")
                    if who and not f.get("lock_stale"):
                        taken.append("%s — %s" % (x, who))
                    else:
                        unlocked.append(x)
            if junk or taken or unlocked:
                parts = []
                if junk:
                    parts.append("Blender's temporary copies are never "
                                 "submitted:\n" + _bullets(junk))
                if taken:
                    parts.append("Locked by someone else — ask them to submit "
                                 "and release:\n" + _bullets(taken))
                if unlocked:
                    parts.append("Lock these before submitting, otherwise you "
                                 "would overwrite a colleague's work:\n"
                                 + _bullets(unlocked))
                raise sc.SvnError("\n\n".join(parts))
            def under_new_dir(x):
                """Файл усередині кинутої теки. `svn status` туди не заходить,
                тож у st такого шляху немає — але додати його все одно треба."""
                parts = x.replace("\\", "/").split("/")[:-1]
                return any(st.get("/".join(parts[:i]), {}).get("status")
                           == "unversioned" for i in range(1, len(parts) + 1))

            fresh = [x for x in paths
                     if st.get(x, {}).get("status") == "unversioned"
                     or (x not in st and under_new_dir(x))]
            gone = [x for x in paths if st.get(x, {}).get("status") == "missing"]
            send = list(paths)
            if fresh:
                # Якщо вибрано теку, svn add додасть її вміст сам. Передавати
                # ще й окремі файли з неї не можна — другий add на той самий
                # файл падає з «уже під версійним контролем».
                fresh = [x for x in fresh
                         if not any(x != d and x.startswith(d + "/")
                                    for d in fresh)]
                sc.add(wc, fresh)
                # svn add --parents заводить і теки-батьки. Якщо не згадати їх
                # у коміті, svn відмовиться: «тека не існує в репозиторії, а її
                # дитина в коміті є». Художник, що перетягнув теку з кадрами,
                # напоровся б на це одразу.
                after = {f["path"]: f for f in sc.status(wc, me=u)}
                have = set(send)
                for x in fresh:
                    parts = x.replace("\\", "/").split("/")[:-1]
                    for i in range(1, len(parts) + 1):
                        d = "/".join(parts[:i])
                        if d not in have and after.get(d, {}).get("status") == "added":
                            send.insert(0, d)      # теки — перед своїм вмістом
                            have.add(d)
            else:
                after = st
            if gone:
                sc.remove(wc, gone)
            # Скільки рядків svn насправді надрукує. Вибраних рядків для цього
            # брати НЕ можна: позначивши одну теку, людина здає тисячі файлів,
            # і поступ показував би «файл 2062 з 1». svn звітує і про теки, тож
            # рахуємо всі записи під вибраним, а не самі лише файли.
            picked = set(send)
            expect, nbytes = 0, 0
            for q, f in after.items():
                if f.get("status") not in ("added", "modified", "deleted",
                                           "replaced"):
                    continue
                if not (q in picked or any(q.startswith(d + "/") for d in picked)):
                    continue
                expect += 1
                # На фазі передачі svn мовчить, тож відсотків там не буде.
                # Але сказати, СКІЛЬКИ саме їде, ми можемо — і людина хоча б
                # розумітиме, чому це триває довго.
                try:
                    nbytes += os.path.getsize(os.path.join(
                        wc, q.replace("/", os.sep)))
                except OSError:
                    pass
            t0 = time.monotonic()
            # Лок після здачі СПАДАЄ — так просив користувач і так поводиться
            # svn за замовчуванням. Зворотний бік реальний: файл із
            # svn:needs-lock тієї ж миті стає read-only, і якщо він відкритий
            # у Blender, наступний Ctrl+S відмовить. Тому про це кажемо в
            # тості, а перемикач лишається під рукою в рядку здачі.
            keep = self.conf.get("prefs", {}).get("keep_locks", False) \
                if keep_locks is None else bool(keep_locks)
            out = sc.commit(wc, send, message, username=u, password=p,
                            progress=self._tick, total=expect or len(send),
                            total_bytes=nbytes or None,
                            rate_hint=self._rate("upload"), keep_locks=keep)
            took = time.monotonic() - t0
            self._learn_rate("upload", nbytes, took)
            if nbytes > 8 * 1024 * 1024 and sc.COMMIT_RE.search(out):
                out += " (%.0f MB in %s, %.1f MB/s)" % (
                    nbytes / 1048576, _mmss(took), nbytes / 1048576 / took)
            if gone and sc.COMMIT_RE.search(out):
                # видалене лишалося на диску, щоб пережити коміт (див. remove)
                sc.purge_deleted(wc, gone)
            # локи навмисно переживають коміт (див. svn_client.commit) —
            # людина має про це знати, інакше файл лишиться зайнятим мовчки
            held = [x for x in paths if st.get(x, {}).get("lock_mine")]
            if held and sc.COMMIT_RE.search(out):
                if keep:
                    out += (" The file stays locked by you — release it when "
                            "you are done." if len(held) == 1 else
                            " %d files stay locked by you — release them when "
                            "you are done." % len(held))
                else:
                    out += (" The file is no longer locked and is read-only "
                            "again — lock it before you keep editing."
                            if len(held) == 1 else
                            " %d files are no longer locked and are read-only "
                            "again — lock them before you keep editing."
                            % len(held))
            return out

        return self._guard(work)

    def relocate(self, new_url):
        """Перевести проєкт на нову адресу сервера — лише за згодою людини."""
        p = self._proj()
        if not p:
            raise sc.SvnError("There is no project")
        new_url = (new_url or "").strip().rstrip("/")
        if not new_url.startswith(("http://", "https://", "svn://", "file:///")):
            raise sc.SvnError("That does not look like a project address.")
        u, pw = self._creds(p)
        out = self._guard(sc.relocate, p["wc"], new_url, username=u, password=pw)
        p["url"] = new_url
        save_conf(self.conf)
        self._last.pop(p["id"], None)
        return out

    # --- провідник проєкту ---
    def browse(self, path=""):
        """Вміст однієї теки. НЕ бере довгий замок: це читання, і людина має
        могти ходити проєктом навіть коли щось передається. Але поки триває
        передача — відступаємо, щоб не смикати робочу копію."""
        if self.busy.is_set():
            raise sc.SvnError("Please wait — a transfer is in progress.")
        wc, (u, p) = self._wc(), self._creds()
        return ex.browse(wc, path, username=u, password=p, remote=True)

    def file_details(self, path):
        if self.busy.is_set():
            raise sc.SvnError("Please wait — a transfer is in progress.")
        return ex.details(self._wc(), path)

    def open_file(self, path, take_lock=False):
        """Відкрити файл у програмі за замовчуванням.

        take_lock=True — спершу зайняти. Це головний шлях: без лока бінарник
        лежить read-only, людина попрацює в ньому годину і не зможе зберегти.
        Список дозволених розширень — бо запуск файлу з мережевої шари це
        запуск чужого коду.
        """
        wc, (u, p) = self._wc(), self._creds()
        full = ex.inside(wc, path)
        if not os.path.isfile(full):
            raise sc.SvnError("That file is no longer there.")
        if not path.lower().endswith(ex.OPENABLE):
            raise sc.SvnError(
                "APSVN does not open files of this kind — use “Show in "
                "folder” and open it yourself if you trust it.")
        if take_lock:
            self._guard(sc.lock, wc, [path], username=u, password=p, me=u)
        try:
            os.startfile(full)
        except OSError as e:
            raise sc.SvnError("Could not open the file: %s" % (e.strerror or e))
        return ("Locked and opened" if take_lock else "Opened")

    def reveal(self, path):
        """Показати файл у Провіднику Windows."""
        full = ex.inside(self._wc(), path)
        try:
            subprocess.run(["explorer.exe", "/select,", os.path.normpath(full)])
        except Exception:
            try:
                os.startfile(os.path.dirname(full))
            except Exception:
                return False
        return True

    def list_new_folder(self, path):
        """Вміст кинутої теки — коли її розгорнули в списку."""
        wc = self._wc()
        full = os.path.join(wc, path.replace("/", os.sep))
        if not os.path.isdir(full):
            raise sc.SvnError("This folder is no longer there.")
        return sc.list_new(wc, path)

    def do_lock(self, paths):
        u, p = self._creds()
        return self._guard(sc.lock, self._wc(), paths, username=u, password=p,
                           me=u)

    def do_unlock(self, paths):
        u, p = self._creds()
        return self._guard(sc.unlock, self._wc(), paths, username=u, password=p)

    def folder_stats(self, path):
        """Скільки в теці файлів, скільки вже наші, скільки чужі.

        Питаємо ДО дії, щоб у діалозі стояли справжні числа, а не обіцянка."""
        if self.busy.is_set():
            raise sc.SvnError("Please wait — a transfer is in progress.")
        wc, (u, p) = self._wc(), self._creds()
        items = sc.files_under(wc, path, remote=True, username=u, password=p)
        return {"total": len(items),
                "mine": sum(1 for i in items if i["mine"]),
                "others": sorted({i["other"] for i in items if i["other"]}),
                "others_n": sum(1 for i in items if i["other"])}

    def lock_folder(self, path):
        u, p = self._creds()

        def work():
            r = sc.lock_folder(self._wc(), path, me=u, username=u, password=p,
                               progress=self._tick)
            msg = "Locked %d of %d files in this folder." % (r["mine"], r["total"])
            if r["others"]:
                who = sorted(set(v for v in r["others"].values() if v))
                msg += (" %d could not be locked — held by %s."
                        % (len(r["others"]), ", ".join(who) or "somebody else"))
            return msg

        return self._guard(work)

    def unlock_folder(self, path):
        u, p = self._creds()

        def work():
            r = sc.unlock_folder(self._wc(), path, username=u, password=p,
                                 progress=self._tick)
            msg = "Released %d files." % r["released"]
            if r["left"]:
                msg += " %d could not be released." % r["left"]
            return msg

        return self._guard(work)

    def do_revert(self, paths):
        self._guard(sc.revert, self._wc(), paths)
        return "Changes discarded"

    def do_resolve(self, paths, keep_mine=True, choice=None):
        """Вивести файл із конфлікту — з рятувальною копією ПЕРЕД тим.

        Копії тут раніше не було зовсім. «Take my colleague's version» стирала
        день роботи безповоротно: .mine svn прибирає тим самим викликом, тож
        повернути її було нізвідки.

        Вид конфлікту з'ясовуємо тут, а не в інтерфейсі: команда, що виводить
        із деревʼяного конфлікту, інша, ніж для текстового, і помилка тут
        мовчазна — файл просто лишається в конфлікті.
        """
        wc = self._wc()
        choice = choice or ("mine" if keep_mine else "theirs")

        def work():
            kinds = {f["path"]: f.get("conflict_kind")
                     for f in sc.status(wc)}
            saved = 0
            for path in paths:
                if choice != "working" and sc.rescue_copy(wc, path, RESCUE):
                    saved += 1
                sc.resolve_conflict(wc, path, kinds.get(path), choice)
            if choice == "working":
                return "Kept the file exactly as it is on your disk now"
            msg = "Conflict resolved"
            if saved:
                msg += (". A copy of the file as it was a moment ago is in "
                        "“Safety copies”")
            return msg

        return self._guard(work)

    def do_cleanup(self):
        return self._guard(sc.cleanup, self._wc())

    def revision_files(self, rev):
        """Список того, що змінилося в коміті — для правої панелі History."""
        u, p = self._creds()
        return self._guard(sc.revision_files, self._wc(), rev,
                           username=u, password=p)

    def get_log(self):
        u, p = self._creds()
        try:
            return sc.log(self._wc(), username=u, password=p)
        except sc.SvnError:
            return []

    # --- історія й відкат окремого файлу ---
    def file_history(self, path):
        wc, (u, p) = self._wc(), self._creds()

        def work():
            rows = sc.file_log(wc, path, username=u, password=p)
            st = {f["path"]: f for f in sc.status(wc, me=u)}
            f = st.get(path, {})
            return {
                "path": path, "rows": rows,
                # відкат поверх незданих змін знищив би їх безповоротно:
                # у pristine лежить BASE, а цих байтів не було ніде
                "dirty": f.get("status") in ("modified", "added", "replaced"),
                "conflicted": f.get("status") == "conflicted",
                "locked_by": (f.get("lock_owner")
                              if f.get("lock_owner") and not f.get("lock_mine")
                              else None),
                "binary": bool(f.get("binary")) or path.lower().endswith(sc.BINARY_EXT),
            }

        return self._guard(work)

    def restore_version(self, path, rev):
        wc, (u, p) = self._wc(), self._creds()

        def work():
            st = {f["path"]: f for f in sc.status(wc, me=u)}
            f = st.get(path, {})
            if f.get("status") in ("modified", "added", "replaced"):
                raise sc.SvnError(
                    "This file has changes you haven’t submitted. Submit "
                    "them or discard them first — otherwise they are gone "
                    "for good.")
            if f.get("status") == "conflicted":
                raise sc.SvnError("Sort out the conflict in this file first.")
            res = sc.restore_revision(wc, path, rev, me=u, username=u,
                                      password=p, rescue_dir=RESCUE,
                                      progress=self._tick)
            msg = ("Done: the file is now the version from commit %s. This "
                   "is NOT on the server yet — click “Submit”." % rev)
            if res.get("was_named") and os.path.basename(res["was_named"]) \
                    != os.path.basename(path):
                msg += (" Back then it was called “%s”."
                        % os.path.basename(res["was_named"]))
            return msg

        return self._guard(work)

    def restore_many(self, rev, items):
        """Повернути кілька файлів до стану з коміту rev.

        ДВА РІЗНІ ВИПАДКИ, і плутати їх не можна:
        * файл у тому коміті ІСНУВАВ (додали чи змінили) — беремо саме rev;
        * файл у тому коміті ВИДАЛИЛИ — у rev його вже немає, брати треба
          rev-1. Інакше людина тисне «повернути» на видаленому файлі й дістає
          «file not found» на дію, яка звучить як «поверни мені його».

        І два різні способи повернення: якщо файл зараз лежить на диску —
        перезаписуємо його вміст (restore_revision, з локом і рятувальною
        копією). Якщо його в копії немає — воскрешаємо через svn copy, бо
        тільки copy тягне за собою історію; cat зробив би файл без роду.

        Один невдалий файл не зупиняє решту: у пачці з тридцяти двох
        обов'язково знайдеться один із неданими змінами, і кидати через нього
        всю роботу — знущання.
        """
        wc, (u, p) = self._wc(), self._creds()
        items = [i for i in (items or []) if isinstance(i, dict) and i.get("path")]
        if not items:
            raise sc.SvnError("Nothing was picked")

        def work():
            try:
                rev_i = int(rev)
            except (TypeError, ValueError):
                raise sc.SvnError("This commit cannot be read")

            # Воскресіння через copy падає з «файл уже існує», якщо копія
            # відстала, тож оновлюємось один раз наперед — але лише коли
            # справді є що воскрешати.
            if any(i.get("action") == "D" or not os.path.exists(
                    os.path.join(wc, i["path"].replace("/", os.sep)))
                   for i in items):
                try:
                    sc.update(wc, username=u, password=p, progress=self._tick)
                except sc.SvnError:
                    pass

            st = {f["path"]: f for f in sc.status(wc, me=u)}
            done, skipped = [], []
            for it in items:
                path = it["path"]
                take = rev_i - 1 if it.get("action") == "D" else rev_i
                if take < 1:
                    skipped.append("%s — there is nothing before that commit"
                                   % path)
                    continue
                f = st.get(path, {})
                if f.get("status") in ("modified", "added", "replaced"):
                    skipped.append("%s — you have unsubmitted changes in it"
                                   % path)
                    continue
                if f.get("status") == "conflicted":
                    skipped.append("%s — sort out its conflict first" % path)
                    continue
                # ЧОМУ НЕ os.path.isfile. Наше `svn delete` іде з --keep-local
                # (інакше зникає 8.3-псевдонім, і файл з апострофом U+02BC уже
                # не назвати в наступному коміті). Тож після видалення байти
                # ЛИШАЮТЬСЯ на диску, а запис у svn зникає — і рішення «файл
                # на місці, отже перезаписуємо» веде до «svn could not find
                # this file». Питаємо не диск, а svn.
                cur = (st.get(path) or {}).get("status")
                full = os.path.join(wc, path.replace("/", os.sep))
                try:
                    if cur == "unversioned":
                        # байти є, але svn їх не знає: рятуємо й прибираємо з
                        # дороги, інакше copy впреться в «файл уже там»
                        sc.rescue_copy(wc, path, RESCUE)
                        os.chmod(full, 0o666)
                        os.unlink(full)
                        sc.restore_deleted(wc, path, take,
                                           username=u, password=p)
                    elif os.path.isfile(full) and cur != "deleted":
                        sc.restore_revision(wc, path, take, me=u, username=u,
                                            password=p, rescue_dir=RESCUE,
                                            progress=self._tick)
                    else:
                        sc.restore_deleted(wc, path, take,
                                           username=u, password=p)
                    done.append(path)
                except (sc.SvnError, OSError) as e:
                    skipped.append("%s — %s" % (path, e))

            if not done:
                raise sc.SvnError("Nothing was brought back:\n"
                                  + _bullets(skipped))
            msg = ("%d file%s brought back to how they were in commit %s. "
                   "This is NOT on the server yet — click “Submit”."
                   % (len(done), "" if len(done) == 1 else "s", rev_i))
            if skipped:
                msg += ("\n\nLeft alone:\n" + _bullets(skipped))
            return msg

        return self._guard(work)

    def save_version_as(self, path, rev):
        """Покласти стару версію окремим файлом — найбезпечніша дія."""
        wc, (u, p) = self._wc(), self._creds()
        stem, ext = os.path.splitext(os.path.basename(path))
        suggest = "%s (commit %s)%s" % (stem, rev, ext)
        r = window.create_file_dialog(webview.SAVE_DIALOG,
                                      directory=wc, save_filename=suggest)
        dest = r[0] if isinstance(r, (list, tuple)) else r
        if not dest:
            return None

        def work():
            sc.save_revision_as(wc, path, rev, dest, username=u, password=p,
                                progress=self._tick)
            return "Saved as a separate copy: %s" % dest

        return self._guard(work)

    def list_deleted(self):
        wc, (u, p) = self._wc(), self._creds()

        def work():
            return sc.deleted_files(wc, username=u, password=p)

        return self._guard(work)

    def restore_deleted(self, path, rev):
        wc, (u, p) = self._wc(), self._creds()

        def work():
            sc.update(wc, username=u, password=p,   # інакше «файл уже існує»
                      progress=self._tick)
            name = sc.restore_deleted(wc, path, rev, username=u, password=p)
            return ("“%s” is back. This is NOT on the server yet "
                    "— click “Submit”." % name)

        return self._guard(work)

    def open_folder(self):
        try:
            os.startfile(self._wc())
            return True
        except Exception:
            return False

    def open_rescue(self):
        try:
            os.makedirs(RESCUE, exist_ok=True)
            os.startfile(RESCUE)
            return True
        except Exception:
            return False

    def pick_folder(self):
        r = window.create_file_dialog(webview.FOLDER_DIALOG)
        return r[0] if r else None


window = None
api = None


def _on_closing():
    """Не дати закрити вікно посеред передачі — це псує робочу копію."""
    if api is not None and api.busy.is_set():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "A transfer is in progress. Please wait — closing now "
                   "could damage the project.", "APSVN", 0x30)
        except Exception:
            pass
        return False
    return True


if __name__ == "__main__":
    try:
        api = Api()
        window = webview.create_window(
            "APSVN", os.path.join(APP_DIR, "ui", "index.html"),
            js_api=api, width=1180, height=760, background_color="#0f1115")
        try:
            window.events.closing += _on_closing
        except Exception:
            pass
        webview.start()
    except SystemExit:
        raise
    except Exception:
        fatal("unexpected error", "APSVN could not continue.",
              traceback.format_exc())
