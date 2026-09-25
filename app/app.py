# -*- coding: utf-8 -*-
"""APSVN — простий SVN-клієнт для художників (стиль Diversion).

Запуск: APSVN.exe (без консолі) або python app/app.py.

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
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse

# залежності вендоряться в ./vendor — застосунок самодостатній, жодних
# pip install у художників. Теку застосунку додаємо явно, бо запуск із
# хвостовим "\" у шляху ламає стандартний sys.path[0].
# Тека з кодом і корінь установки — це тепер РІЗНІ речі: код в app/, а
# ui/, vendor/, runtime/ і svn/ лежать поруч із нею, на рівень вище.
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(CODE_DIR)
sys.path.insert(0, CODE_DIR)
sys.path.insert(0, os.path.join(APP_DIR, "vendor"))

# Єдиний модуль, який знає, під якою системою ми працюємо. Імпортується ДО
# всього іншого, бо CONF_DIR нижче вже питає в нього шлях.
import desktop  # noqa: E402

CONF_DIR = desktop.conf_dir("APSVN")
CONF = os.path.join(CONF_DIR, "config.json")
LOG = os.path.join(CONF_DIR, "error.log")
RESCUE = os.path.join(CONF_DIR, "rescue")
# Номер версії — єдине місце на весь проєкт. Збірка бере його звідси,
# і оновлення порівнюватиме його з тим, що лежить на сервері.
VERSION = "1.1.0"

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
    desktop.message_box("APSVN — " + title,
                        "%s\n\nDetails: %s" % (text, LOG))
    sys.exit(1)


try:
    import keyring
    import webview
    import svn_client as sc
    import explorer as ex
    import shellicon as si
    import updater as up
    import server_api as srv
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


def _thumb(full):
    """Картинка локального файлу — за ВМІСТОМ, а не за іменем.

    Копії, які svn лишає поруч при конфлікті, звуться «scene.blend.r12»: за
    розширенням їх не впізнати, а розбір заголовка впізнає. Нічого не кидає.
    """
    if not full or not os.path.isfile(full):
        return None
    try:
        import base64
        import blendthumb
        import imgthumb
        got = blendthumb.blend_thumbnail(full)
        if got:
            return "data:image/png;base64," + base64.b64encode(got[2]).decode("ascii")
        return imgthumb.preview_data_uri(full)
    except Exception:
        return None


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
        self._srv = {}                     # що вміє сервер — по проєктах
        self._tasks = {}                   # задачі — по проєктах
        self._versions = {}                # версії файлу з ключами вмісту
        self._img = srv.ImageCache()       # прев'ю з сервера
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

    def open_link(self, url):
        """Відкрити посилання в браузері — ЛИШЕ наше власне.

        Адреса сюди приходить із відповіді GitHub, тобто зовні. Відкривати
        будь-що, що прийшло по мережі, означало б віддати чужому
        серверу право запускати що завгодно на машині художника.
        Перевірка в один рядок, ціна помилки — неприємна.
        """
        u = str(url or "")
        if not u.startswith("https://github.com/" + up.REPO):
            return False
        return desktop.open_path(u)

    # --- оновлення самої програми ---
    def check_update(self):
        """Що є на сервері. Ніколи не кидає — інтерфейс сам вирішує, як сказати."""
        return up.check(VERSION)

    def do_update_app(self):
        """Завантажити нову збірку, розкласти поруч і передати підміну назовні.

        Програма не може замінити сама себе на ходу: Windows тримає файли, які
        зараз виконуються, а серед них і python, яким ми працюємо. Тож тут ми
        доводимо справу до «все готове й перевірене», запускаємо окремий
        сценарій — і виходимо. Він дочекається, поки нас не стане, і аж тоді
        поміняє теки.

        Повертає текст для останнього вікна перед закриттям.
        """
        if self.busy.is_set():
            raise sc.SvnError("A transfer is in progress \u2014 finish it first")

        info = up.check(VERSION)
        if info.get("state") != "ok":
            raise sc.SvnError("Could not reach the update server")
        if not info.get("newer"):
            return "You already have the newest version"
        if not info.get("download"):
            raise sc.SvnError("This release has no build for your system")

        work = up.work_dir()
        os.makedirs(work, exist_ok=True)
        zip_path = os.path.join(work, info["name"])

        # Поступ тим самим каналом, що й передача файлів: художник уже знає
        # цю смужку, вигадувати для оновлення другу немає сенсу.
        def on_bytes(got, total):
            self._prog = {"phase": "files", "kind": "download",
                          "done": got >> 20, "total": (total or 0) >> 20,
                          "pct": int(got * 100 / total) if total else None,
                          "name": info["name"]}

        self.busy.set()
        try:
            up.download(info["download"], zip_path, size=info.get("size"),
                        progress=on_bytes)
            staged = up.stage(zip_path, os.path.join(work, "staged"))
        finally:
            self.busy.clear()
            self._prog = None

        # На маку підміняється .app цілком: код у ньому лише частина, поруч
        # лежать свій Python і свій svn, а зверху підпис. Раніше тут стояв
        # APP_DIR — тобто Contents/Resources, — і оновлення підмінило б саму
        # теку з кодом усередині старого bundle. Заразом це робить правильним
        # і `open` у сценарії підміни: відкрити можна .app, а не теку.
        install = desktop.app_bundle(APP_DIR) or APP_DIR
        relaunch = up.relaunch_target(staged, install)
        script = up.write_swap_script(work, staged, install, os.getpid(),
                                      relaunch)
        self._pending_update = script
        return ("APSVN %s is ready. The program will close and reopen by "
                "itself \u2014 give it a moment." % info["want"])

    def finish_update(self):
        """Запустити підміну й закритися. Кличеться інтерфейсом ОСТАННІМ."""
        script = getattr(self, "_pending_update", None)
        if not script:
            return False
        up.launch_detached(script)
        global _updating
        _updating = True                # щоб _on_closing не заважав
        try:
            window.destroy()
        except Exception:
            os._exit(0)
        return True

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

    # --- сервер студії: задачі, прев'ю, залежності ---------------------------
    #
    # Усе тут — ДОПОВНЕННЯ до svn, а не його частина. Тому:
    # * жоден із цих викликів не бере self._lock — картинка не має чекати, поки
    #   доїде коміт, а задача — поки скачається проєкт;
    # * svn тут не кличеться, поки йде передача: svn поруч зі svn на тій самій
    #   копії впирається в її замок, і _run кинувся б «лагодити» її посеред
    #   чужої операції. Потрібне про копію береться з останнього state();
    # * помилка сервера не стає помилкою програми. Немає сервера — немає
    #   картинок і задач, а все інше працює, як працювало.

    def _where(self, p=None):
        """(де API, з якої теки сховища знято копію).

        None — сервер цього проєкту не svn-native, і питати нема кого.
        False — поки невідомо (копію ще не читали, а зараз іде передача).
        """
        p = p or self._proj()
        if not p:
            return None
        info = (self._last.get(p["id"]) or {}).get("info")
        if not info:
            if self.busy.is_set() or not p.get("wc") or \
                    not os.path.isdir(p["wc"]):
                return False
            try:
                info = sc.info(p["wc"])
            except sc.SvnError:
                return False
        root, url = info.get("root") or "", info.get("url") or ""
        loc = srv.locate(root)
        if loc is None:
            return None
        rel = urllib.parse.unquote(url[len(root):]).strip("/") \
            if url.startswith(root) else ""
        return loc, ("/" + rel) if rel else ""

    def _client(self, p=None):
        p = p or self._proj()
        w = self._where(p)
        if not w:
            return None, ""
        u, pw = self._creds(p)
        return srv.Client(w[0], u, pw), w[1]

    def server_status(self, force=False):
        """Що вміє сервер поточного проєкту.

        Відповідь пам'ятаємо: успіх — на 10 хвилин, невдачу — на хвилину, а
        відмову в паролі — на п'ять. Питати щоразу нема сенсу, а після
        невдачі тим паче: хибний пароль, повторений щодесять секунд, сервер
        сприйме як підбір і зачинить вхід (429) — і вже для всього.
        """
        p = self._proj()
        if not p:
            return {"ok": False}
        memo = self._srv.get(p["id"])
        if memo and not force and time.time() < memo["until"]:
            return memo["out"]
        w = self._where(p)
        if w is False:
            return {"ok": False, "why": "later"}      # не пам'ятаємо — це мить
        if w is None:
            out, ttl = {"ok": False, "why": "none"}, 600
        else:
            u, pw = self._creds(p)
            client = srv.Client(w[0], u, pw)
            try:
                h = client.hello()
                eps = [str(e) for e in (h.get("endpoints") or [])]
                out = {"ok": True, "me": h.get("user") or u,
                       "admin": bool(h.get("admin")),
                       # старий образ сервера вмів прев'ю, але не задачі
                       "tasks": any(e.rstrip("/").endswith("/tasks") for e in eps),
                       "repo": client.where.repo}
                ttl = 600
            except srv.ApiError as e:
                out = {"ok": False, "why": "error", "error": str(e),
                       "code": e.code}
                ttl = 300 if e.code in (401, 429) else 60
        self._srv[p["id"]] = {"out": out, "until": time.time() + ttl}
        return out

    def _task_view(self, t, prefix, me, wc):
        """Задача з сервера -> те, що треба інтерфейсу, з шляхом у копії."""
        local = srv.local_path(prefix, t.get("path"))
        status = t.get("status") or ""
        people = [str(x) for x in (t.get("assignees") or [])]
        mine = bool(me) and me in people
        full = (os.path.join(wc, local.replace("/", os.sep))
                if (wc and local is not None) else None)
        return {
            "id": t.get("id"), "path": t.get("path"), "local": local,
            "name": t.get("name") or (t.get("path") or "").rsplit("/", 1)[-1],
            "type": t.get("type") or "", "status": status,
            "status_name": t.get("status_name") or
            srv.STATUS_NAMES.get(status, status),
            "assignees": people, "mine": mine,
            "due": t.get("due"), "overdue": bool(t.get("overdue")),
            "updated": t.get("updated"), "gone": bool(t.get("gone")),
            "is_dir": bool(full and os.path.isdir(full)),
            "on_disk": bool(full and os.path.isfile(full)),
            "binary": bool(local) and local.lower().endswith(sc.BINARY_EXT),
            "openable": bool(local) and local.lower().endswith(ex.OPENABLE),
            # лише ті кроки, які виконавцю дозволені; решта — справа керівника,
            # і кнопка, що завжди відповідає 403, людину лише дратує
            "moves": [to for to in ("wip", "wfa")
                      if mine and (status, to) in srv.ARTIST_MOVES],
        }

    def tasks_overview(self, force=False):
        """Незавершені задачі проєкту: мої — для вкладки, чужі — для позначок.

        Чужі теж потрібні: «цей файл призначено olena» людина має бачити ДО
        того, як спробує його зайняти, а не з відмови сервера.
        """
        p = self._proj()
        if not p:
            return {"ok": False, "tasks": []}
        memo = self._tasks.get(p["id"])
        if memo and not force and time.time() - memo["at"] < 40:
            return memo["out"]
        s = self.server_status()
        if not s.get("ok") or not s.get("tasks"):
            return {"ok": False, "tasks": [], "off": True,
                    "error": s.get("error")}
        client, prefix = self._client(p)
        if client is None:
            return {"ok": False, "tasks": [], "error": srv.OFFLINE}
        try:
            got = client.tasks(status=srv.ACTIVE)
        except srv.ApiError as e:
            # Останній відомий список лишається: позначки «призначено колезі»
            # на хвилину застарілі кращі, ніж зниклі посеред роботи.
            stale = dict((memo or {}).get("out") or {"tasks": []})
            stale.update(ok=False, error=str(e))
            return stale
        me = s.get("me") or p.get("username")
        tasks = [self._task_view(t, prefix, me, p.get("wc"))
                 for t in got.get("tasks") or []]
        out = {"ok": True, "me": me, "tasks": tasks}
        self._tasks[p["id"]] = {"at": time.time(), "out": out}
        return out

    def _tasks_stale(self):
        """Наступний tasks_overview() має спитати сервер — але список не губимо.

        Не pop: якщо сервер зникне саме після зміни статусу, запасним лишиться
        останній відомий список, і позначки «призначено колезі» не щезнуть
        посеред роботи. Перевірено test_server.py саме таким обривом.
        """
        memo = self._tasks.get(self.c.get("id"))
        if memo:
            memo["at"] = 0

    def tasks_done(self):
        """Мої завершені задачі — лише на вимогу, списком не більше 50."""
        s = self.server_status()
        client, prefix = self._client()
        if client is None or not s.get("ok"):
            raise sc.SvnError(s.get("error") or srv.OFFLINE)
        try:
            got = client.tasks(mine=True, status=["done"])
        except srv.ApiError as e:
            raise sc.SvnError(str(e))
        p = self._proj()
        rows = [self._task_view(t, prefix, s.get("me"), p.get("wc"))
                for t in got.get("tasks") or []]
        return rows[:50]

    def task_detail(self, task_id):
        """Задача зі стрічкою подій і картинкою файлу."""
        s = self.server_status()
        client, prefix = self._client()
        if client is None or not s.get("ok"):
            raise sc.SvnError(s.get("error") or srv.OFFLINE)
        try:
            got = client.task(task_id)
        except srv.ApiError as e:
            raise sc.SvnError(str(e))
        t = got.get("task") or {}
        p = self._proj()
        view = self._task_view(t, prefix, s.get("me"), p.get("wc"))
        view["supervisor"] = bool(got.get("supervisor"))
        view["created_by"] = t.get("created_by")
        # новіші зверху — як у стрічці, яку людина гортає вниз у минуле
        view["events"] = [{k: e.get(k) for k in ("at", "user", "kind", "old",
                                                 "new", "comment", "rev")}
                          for e in reversed(t.get("events") or [])][:200]
        view["preview"] = None
        if not view["is_dir"] and (t.get("path") or "").lower().endswith(
                srv.PREVIEWABLE):
            view["preview"] = self._preview(client, t["path"], None)
        return view

    def task_move(self, task_id, status, comment=""):
        """Новий статус задачі. Правила перевіряє сервер; 403 — це правило."""
        if status not in srv.STATUS_NAMES:
            raise sc.SvnError("Unknown status")
        client, _ = self._client()
        if client is None:
            raise sc.SvnError(srv.OFFLINE)
        try:
            got = client.set_status(task_id, status, (comment or "").strip())
        except srv.ApiError as e:
            # «Moving to Done is up to a supervisor.» — пояснення від сервера,
            # і воно заслуговує вікна, а не тосту
            raise (sc.RuleError(str(e)) if e.code == 403 else sc.SvnError(str(e)))
        self._tasks_stale()
        t = got.get("task") or {}
        return "“%s” — %s now." % (t.get("name") or "The task",
                                   t.get("status_name") or
                                   srv.STATUS_NAMES[status])

    def task_comment(self, task_id, text):
        text = (text or "").strip()
        if not text:
            raise sc.SvnError("Write something first")
        client, _ = self._client()
        if client is None:
            raise sc.SvnError(srv.OFFLINE)
        try:
            client.comment(task_id, text)
        except srv.ApiError as e:
            raise sc.SvnError(str(e))
        return "Comment added"

    def open_web(self, kind, path=None):
        """Сторінка на сайті студії — збирається ТУТ, а не приходить ззовні.

        Інтерфейс каже лише «що» (файл, мої задачі, дошка) і шлях у копії;
        адресу складаємо самі з адреси проєкту. Так інтерфейс не може
        попросити відкрити будь-що, і нічого чужого в браузер не потрапить.
        """
        w = self._where()
        if not w:
            raise sc.SvnError("This project’s server has no website.")
        loc, prefix = w
        repo = urllib.parse.quote(loc.repo, safe="")
        if kind == "mine":
            url = loc.web + "mine"
        elif kind == "board":
            url = loc.web + repo + "/tasks/"
        elif kind in ("file", "repo"):
            # file — шлях у копії; repo — шлях від кореня сховища (задача на
            # гілці, якої в копії немає, теж має сторінку)
            rp = (srv.repo_path(prefix, path or "") if kind == "file"
                  else "/" + str(path or "").strip("/")).strip("/")
            if ".." in rp.split("/"):
                raise sc.SvnError("Unknown page")
            url = loc.web + repo + "/tree/" + urllib.parse.quote(rp, safe="/")
        else:
            raise sc.SvnError("Unknown page")
        if not desktop.open_path(url):
            raise sc.SvnError("Could not open the browser")
        return True

    # --- картинки з сервера ---
    def _preview(self, client, rpath, rev):
        """data:URI картинки файлу на ревізії (None — остання), або None.

        Готове пам'ятаємо: вміст на ревізії не змінюється ніколи. «Остання» —
        змінюється, тож її ключ живе хвилину. Відсутність картинки не
        запам'ятовуємо зовсім: «готується» за хвилину стане готовою.
        """
        stamp = rev if rev is not None else "head-%d" % (time.time() // 60)
        key = ("p", client.where.api, client.where.repo, rpath, stamp)
        if self._img.has(key):
            return self._img.get(key)
        got = client.preview(rpath, rev)
        uri = srv.data_uri(*got) if got else None
        if uri:
            self._img.put(key, uri)
        return uri

    def _blob(self, client, key, link):
        """Картинка за ключем вмісту — однакова для всіх версій з тим вмістом."""
        ck = ("b", client.where.api, key)
        if self._img.has(ck):
            return self._img.get(ck)
        got = client.blob(link)
        uri = srv.data_uri(*got) if got else None
        if uri:
            self._img.put(ck, uri)
        return uri

    def previews(self, items):
        """Картинки файлів із сервера: {"шлях@ревізія": data:URI або None}.

        Для того, чого ще немає на диску, для файлів у коміті з історії, для
        старих версій. Нічого не кидає: картинка — прикраса, і її відсутність
        не варта повідомлення.
        """
        out = {}
        if not self.server_status().get("ok"):
            return out
        client, prefix = self._client()
        if client is None:
            return out
        want = []
        for it in (items or [])[:80]:
            path = str((it or {}).get("path") or "")
            rev = it.get("rev")
            try:
                rev = int(rev) if rev not in (None, "") else None
            except (TypeError, ValueError):
                rev = None
            if path.lower().endswith(srv.PREVIEWABLE):
                want.append((path, rev))
        got = srv.fetch_all(
            lambda pr: self._preview(client, srv.repo_path(prefix, pr[0]), pr[1]),
            want)
        for (path, rev), uri in zip(want, got):
            out["%s@%s" % (path, "" if rev is None else rev)] = uri
        return out

    def file_versions(self, path):
        """Картинки версій файлу для «What happened to …» — за ревізіями.

        Сервер сам іде крізь перейменування і дає ключ вмісту кожної версії;
        однаковий вміст (тег, переїзд) — одна картинка, і качаємо її раз.
        """
        if not self.server_status().get("ok"):
            return {"ok": False}
        client, prefix = self._client()
        if client is None:
            return {"ok": False}
        try:
            got = client.versions(srv.repo_path(prefix, path), limit=40)
        except srv.ApiError as e:
            return {"ok": False, "error": str(e)}
        vs = got.get("versions") or []
        self._versions[(self.c.get("id"), path)] = {
            v["key"]: v.get("rev") for v in reversed(vs) if v.get("key")}
        links = {}
        for v in vs:
            pv = v.get("preview") or {}
            if pv.get("state") == "ok" and pv.get("url") and v.get("key"):
                links.setdefault(v["key"], pv["url"])
        keys = list(links)[:24]
        uris = srv.fetch_all(lambda k: self._blob(client, k, links[k]), keys)
        by_key = dict(zip(keys, uris))
        return {"ok": True, "versions": {
            str(v.get("rev")): {"preview": by_key.get(v.get("key")),
                                "state": (v.get("preview") or {}).get("state")}
            for v in vs}}

    def which_version(self, path):
        """Яка з версій лежить у людини на диску — за SHA-1, нічого не качаючи.

        Потрібно тоді, коли svn цього не скаже: файл змінено (скажімо, людина
        щойно повернула стару версію і ще не здала), а вміст збігається з
        однією з версій. Читає файл цілком, тож лише на вимогу.
        """
        known = self._versions.get((self.c.get("id"), path))
        if not known:
            return None
        full = ex.inside(self._wc(), path)
        if not os.path.isfile(full):
            return None
        try:
            key = srv.content_key(full)
        except OSError:
            return None
        return {"rev": known.get(key)}

    def file_links(self, path):
        """Що сцена тягне за собою і хто використовує файл — для провідника."""
        if not self.server_status().get("ok"):
            return {"ok": False}
        client, prefix = self._client()
        if client is None:
            return {"ok": False}
        rp = srv.repo_path(prefix, path)
        low = path.lower()
        out = {"ok": True}
        if low.endswith(".blend"):
            try:
                out["deps"] = self._deps_view(client.deps(rp, recursive=True),
                                              prefix)
            except srv.ApiError as e:
                out["deps"] = {"state": "error", "note": str(e)}
        if low.endswith(srv.USABLE):
            try:
                got = client.usedby(rp)
                users = [srv.local_path(prefix, u.get("source")) or u.get("source")
                         for u in got.get("users") or []]
                out["used_by"] = {"users": users[:60], "n": len(users),
                                  "complete": bool(got.get("complete"))}
            except srv.ApiError as e:
                out["used_by"] = {"error": str(e)}
        return out

    def _deps_view(self, d, prefix):
        """Відповідь deps (буває 180 КБ на одну сцену) -> коротке зведення.

        Інтерфейсу не треба кожне запаковане зображення поіменно — йому треба
        «скільки чого» і перелік того, що справді зламано. Плюс перетин із
        тим, що зараз їде з сервера: «сцена тягне файли, які колега щойно
        змінив» — рівно та порада, яку варто дати перед відкриттям.
        """
        state = d.get("state") or "error"
        if state != "ok":
            return {"state": state, "note": d.get("note") or ""}
        links = d.get("links") or []
        counts = {}
        for l in links:
            counts[l.get("state")] = counts.get(l.get("state"), 0) + 1
        problems = []
        for l in links:
            if l.get("state") in srv.PROBLEMS and len(problems) < 40:
                raw = l.get("raw") or ""
                problems.append({
                    "name": l.get("name") or raw.replace("\\", "/").rsplit("/", 1)[-1],
                    "raw": raw, "state": l.get("state"), "kind": l.get("kind"),
                    "target": srv.local_path(prefix, l["target"])
                    if l.get("target") else None})
        closure = d.get("closure") or {}
        files = [x for x in (srv.local_path(prefix, f.get("path"))
                             for f in closure.get("files") or []) if x]
        pid = self.c.get("id")
        incoming = {f["path"] for f in (self._last.get(pid) or {}).get("files", [])
                    if f.get("remote_change")}
        newer = [f for f in files if f in incoming]
        return {"state": "ok", "blender": d.get("blender"), "total": len(links),
                "counts": counts, "problems": problems, "uses": len(files),
                "newer": newer[:20], "newer_n": len(newer),
                "pending": len(closure.get("pending") or [])}

    def used_by_many(self, paths):
        """{файл: [сцени, що на нього посилаються]} — перед здачею видалення.

        Сцени, які видаляються тим самим комітом, не рахуються: попереджати,
        що зламається те, що теж зникає, — шум.
        """
        if not self.server_status().get("ok"):
            return {}
        client, prefix = self._client()
        if client is None:
            return {}
        going = set(paths or [])
        want = [p for p in (paths or []) if str(p).lower().endswith(srv.USABLE)][:40]

        def one(p):
            got = client.usedby(srv.repo_path(prefix, p))
            users = [srv.local_path(prefix, u.get("source")) or u.get("source")
                     for u in got.get("users") or []]
            return [u for u in users if u not in going]

        res = srv.fetch_all(one, want)
        return {p: u for p, u in zip(want, res) if u}

    def conflict_previews(self, path):
        """Обидві сторони конфлікту картинками — щоб вибирати, бачачи.

        Зі свого диска: svn лишає поруч копію того, що приїхало від колеги
        (file.r12), а для тексту ще й file.mine. Сервер питаємо лише тоді,
        коли копії колеги на диску немає — як у конфлікті «твій файл на місці
        командного». Нічого не кидає: без картинок діалог лишається тим самим.
        """
        try:
            full = ex.inside(self._wc(), path)
        except sc.SvnError:
            return {}
        folder, name = os.path.split(full)
        theirs, theirs_rev, mine = None, None, None
        try:
            for n in os.listdir(folder):
                tail = n[len(name):] if n.startswith(name) else ""
                if tail.startswith(".r") and tail[2:].isdigit():
                    if theirs_rev is None or int(tail[2:]) > theirs_rev:
                        theirs_rev, theirs = int(tail[2:]), os.path.join(folder, n)
                elif tail == ".mine":
                    mine = os.path.join(folder, n)
        except OSError:
            pass
        out = {"mine": _thumb(mine or full), "theirs": _thumb(theirs),
               "theirs_rev": theirs_rev}
        if out["theirs"] is None and path.lower().endswith(srv.PREVIEWABLE) \
                and self.server_status().get("ok"):
            client, prefix = self._client()
            if client is not None:
                try:
                    out["theirs"] = self._preview(
                        client, srv.repo_path(prefix, path), theirs_rev)
                except srv.ApiError:
                    pass
        return out

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
        self._srv.pop(pid, None)
        self._tasks.pop(pid, None)
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
        # Відповідь сервера пам'ятається хвилинами (див. server_status) — зі
        # старим паролем вона була б «не пускає» ще довго після виправлення.
        self._srv.pop(p["id"], None)
        self._tasks.pop(p["id"], None)
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

    def do_commit(self, paths, message, keep_locks=None, review=None):
        """Здати вибране. review — id задач, які після здачі піти на перевірку.

        Статус «в роботу» тут не ставиться НАВМИСНО: перший коміт виконавця
        сервер переводить у роботу сам, за кілька секунд. Зробити це ще й тут —
        значить подвоїти подію в стрічці задачі.
        """
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
            done = sc.COMMIT_RE.search(out)
            if review and done:
                out += self._send_to_review(review, message, done.group(1))
            return out

        return self._guard(work)

    def _send_to_review(self, ids, message, rev):
        """Після здачі — задачі на перевірку. Ніколи не валить саму здачу.

        Коміт уже на сервері; якщо статус не змінився (сервер недоступний,
        правило не пустило), людина має про це дізнатися, але повідомлення
        «здача не вдалася» було б неправдою.

        Порядок з автостартом сервера байдужий: він переводить у роботу лише
        з To do і Retake, тож задачу, яку ми вже віддали на перевірку, не
        чіпає; а якщо встиг першим — з роботи на перевірку виконавцю можна.
        """
        client, _ = self._client()
        if client is None:
            return (" The task could not be sent to review — the server "
                    "is not answering. Do it from the “My tasks” tab.")
        moved, failed = [], []
        for tid in ids or []:
            try:
                got = client.set_status(int(tid), "wfa",
                                        "%s\n(commit %s)" % (message, rev))
                moved.append((got.get("task") or {}).get("name") or "#%s" % tid)
            except (srv.ApiError, ValueError, TypeError) as e:
                failed.append(str(e))
        self._tasks_stale()                        # показати новий статус одразу
        msg = ""
        if moved:
            msg += " Sent to review: %s." % ", ".join("“%s”" % n for n in moved)
        if failed:
            msg += (" The task was not sent to review: %s"
                    % "; ".join(sorted(set(failed))))
        return msg

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
        self._srv.pop(p["id"], None)          # новий сервер — нове API
        self._tasks.pop(p["id"], None)
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
            self._lock_explained(wc, [path], u, p)
        if not desktop.open_path(full):
            raise sc.SvnError("Could not open the file")
        return ("Locked and opened" if take_lock else "Opened")

    def reveal(self, path):
        """Показати файл у провіднику системи, виділивши саме його."""
        full = ex.inside(self._wc(), path)
        return desktop.reveal(full) or desktop.open_path(os.path.dirname(full))

    def list_new_folder(self, path):
        """Вміст кинутої теки — коли її розгорнули в списку."""
        wc = self._wc()
        full = os.path.join(wc, path.replace("/", os.sep))
        if not os.path.isdir(full):
            raise sc.SvnError("This folder is no longer there.")
        return sc.list_new(wc, path)

    def do_lock(self, paths):
        u, p = self._creds()
        return self._lock_explained(self._wc(), paths, u, p)

    def _lock_explained(self, wc, paths, u, p):
        """Лок — а якщо сервер відмовив без пояснень, пояснюємо задачами.

        Хук м'якого локу пише, чий це файл, і svn доносить цей текст сам —
        тоді приходить RuleError, і додати нічого. Але якщо текст загубився
        дорогою (голе «403 Forbidden»), людина лишилася б із відмовою без
        причини. Причину ми знаємо самі: задача на цьому файлі призначена
        комусь іншому. Лише тоді, коли відмова справді схожа на правило —
        інакше «призначено olena» підмінило б зовсім іншу біду.
        """
        try:
            return self._guard(sc.lock, wc, paths, username=u, password=p,
                               me=u)
        except sc.RuleError:
            raise
        except sc.SvnError as e:
            why = self._assigned_elsewhere(paths, "lock")
            if why and re.search(r"\b403\b|Forbidden|hook", e.raw or "", re.I):
                raise sc.RuleError(why, e.raw)
            raise

    def _assigned_elsewhere(self, paths, verb):
        """Той самий текст, що пише хук м'якого локу, — з відомих нам задач."""
        me = self.c.get("username")
        tasks = ((self._tasks.get(self.c.get("id")) or {}).get("out")
                 or {}).get("tasks") or []
        lines = []
        for path in paths:
            for t in srv.covering(tasks, path):
                if t["assignees"] and me not in t["assignees"] \
                        and t["status"] != "done":
                    lines.append("  %s — %s (%s, %s)" % (
                        path, ", ".join(t["assignees"]), t["type"] or "task",
                        t["status_name"]))
                    break
        if not lines:
            return None
        return ("These files are assigned to someone else:\n" + "\n".join(lines)
                + "\nOnly the assignee or a supervisor can %s them. Ask a "
                  "supervisor to reassign the task." % verb)

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
            if r.get("refused"):
                # Вікном, а не тостом: пояснення від сервера — на кілька
                # рядків, і воно каже, до кого йти по решту файлів.
                raise sc.RuleError(msg + "\n\n" + r["refused"])
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
            # На якій ревізії стоїть сам файл у копії. Версія, яка в людини, —
            # найновіша з історії, не новіша за неї: «ось ця — у тебе». Питаємо
            # копію, а не сервер, тож це миттєво й без мережі.
            try:
                base = int(sc.file_info(wc, path)["rev"])
            except (sc.SvnError, TypeError, ValueError, KeyError):
                base = None
            return {
                "path": path, "rows": rows, "base": base,
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

    # ІНТЕРФЕЙС ЦИХ ДВОХ НЕ КЛИЧЕ — і це навмисно, а не забуто.
    #
    # Був окремий екран «що зникло»: 200 комітів від початку, лише те, що досі
    # відсутнє. Його прибрали, бо на живому проєкті він не показав жодного
    # випадку, заради якого існував, а місце в інтерфейсі коштує щодня. Але
    # питання, на яке він відповідав, нікуди не поділося: «файл зник, а коли —
    # не знаю». Історія бачить лише 40 останніх комітів і вимагає знати, у
    # якому саме шукати.
    #
    # Тож код лишається робочим і перевіреним. Якщо хтось скаже «я загубив
    # файл і не можу знайти» — повернути екран коштує десяток рядків у
    # ui/app.js. Видалити це зараз означало б писати те саме вдруге.
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
        return desktop.open_path(self._wc())

    def open_rescue(self):
        try:
            os.makedirs(RESCUE, exist_ok=True)
            desktop.open_path(RESCUE)
            return True
        except Exception:
            return False

    def pick_folder(self):
        r = window.create_file_dialog(webview.FOLDER_DIALOG)
        return r[0] if r else None


window = None
_updating = False       # іде підміна: закриття тоді не треба зупиняти
api = None


def _on_closing():
    """Не дати закрити вікно посеред передачі — це псує робочу копію."""
    if _updating:
        return True
    if api is not None and api.busy.is_set():
        desktop.message_box("APSVN",
                            "A transfer is in progress. Please wait — "
                            "closing now could damage the project.", warn=True)
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
        # Іконку ставимо ПІСЛЯ того, як вікно з'явилось: до того шукати нема
        # чого. pywebview кличе цю функцію вже з піднятим інтерфейсом.
        def _dress():
            for _ in range(20):            # вікно з'являється не миттєво
                if desktop.set_window_icon("APSVN",
                                           os.path.join(APP_DIR, "ui", "apsvn.ico")):
                    return
                time.sleep(0.25)

        webview.start(_dress)
    except SystemExit:
        raise
    except Exception:
        fatal("unexpected error", "APSVN could not continue.",
              traceback.format_exc())
