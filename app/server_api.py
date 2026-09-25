# -*- coding: utf-8 -*-
"""Місток до сервера студії (svn-native): прев'ю, залежності .blend, задачі.

Поруч із самим SVN сервер віддає /api/v1 — картинки файлів, що тягне за собою
сцена, хто її використовує, і задачі зі статусами Kitsu. Цей модуль — єдине
місце в APSVN, яке з ним говорить.

ЧОГО ТУТ НЕМАЄ НАВМИСНО:

* Жодного svn. Файли на диску — справа svn_client; сервер лише ДОПОВНЮЄ
  картину. Немає сервера (інша програма, старий образ, офлайн) — APSVN
  працює як працював, тільки без картинок і задач. Тому кожна невдача тут —
  ApiError з людським текстом, і жодна не валить дію svn поруч.
* Переходів за редиректами. urllib повторює запит на нову адресу З ТИМ САМИМ
  заголовком Authorization — навіть на інший домен. Сервер, що відповів би
  302 кудись назовні, отримав би пароль художника. Редирект тут — помилка.
* Абсолютних посилань із відповіді. Прев'ю сервер віддає відносними
  (/api/v1/blobs/…?s=…); качаємо їх лише з того самого origin, звідки
  прийшла сама відповідь.
* Здогадів про адресу. API шукаємо лише там, де його обіцяє розкладка
  svn-native: https://host/svn/<repo> -> https://host/api/v1/. Слати логін
  навмання на адресу, якої ніхто не обіцяв, не варто навіть тому самому хосту.
"""
import base64
import collections
import hashlib
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TIMEOUT = 12                 # секунд на запит: сервер у студії або поруч, або ніде
MAX_JSON = 16 << 20          # стеля відповіді; дерево на кілька тисяч файлів — сотні КБ
MAX_IMAGE = 8 << 20          # мініатюра — десятки КБ; більше означає, що це не мініатюра
WORKERS = 4                  # паралельних завантажень картинок

# Статуси — ті самі короткі ключі, що в Kitsu (так вирішив сервер, щоб
# синхронізація потім лягла без перейменувань). Назви — як їх бачить людина.
STATUS_NAMES = {"todo": "To do", "wip": "In progress", "wfa": "Review",
                "retake": "Retake", "done": "Done"}
ACTIVE = ("todo", "wip", "wfa", "retake")

# Що виконавець може сам. Сервер правила перевіряє і так (403 з поясненням);
# тут вони лише для того, щоб не показувати кнопок, які точно відмовлять.
ARTIST_MOVES = {("todo", "wip"), ("todo", "wfa"), ("wip", "wfa"),
                ("wfa", "wip"), ("retake", "wip"), ("retake", "wfa")}

# Стани посилань .blend, які справді ламають сцену (admin/deplinks.py).
# «external» серед них НЕМАЄ навмисно: абсолютний шлях поза проєктом за
# конвенцією студії означає «живцем зі сховища» (X:\…) — так і задумано.
PROBLEMS = ("missing", "case", "absolute", "outside")

# Що сервер уміє показати картинкою (admin/previews.py на сервері). Про інше
# не питаємо зовсім: 404 на кожен .fbx — це запити, які нічого не дадуть.
PREVIEWABLE = (".blend", ".psd", ".psb", ".png", ".jpg", ".jpeg", ".webp",
               ".gif", ".bmp", ".tga", ".tif", ".tiff")

# Що може бути залежністю .blend (admin/deplinks.py на сервері) — лише для
# таких файлів має сенс питати «хто мене використовує».
USABLE = (".blend", ".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr",
          ".hdr", ".bmp", ".webp", ".gif", ".psd", ".dds", ".jp2", ".cin",
          ".dpx", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpg", ".mpeg",
          ".ogv", ".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a", ".ttf",
          ".otf", ".woff", ".woff2", ".pfb", ".abc", ".usd", ".usda", ".usdc",
          ".usdz", ".vdb")

# Картинки, які ми погоджуємось показати. Не «будь-що image/*»: SVG — це
# документ зі скриптами, і вбудовувати його в інтерфейс ми не станемо.
_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

OFFLINE = "No connection to the server."
AUTH = ("The server did not accept your user name or password for tasks and "
        "previews.")
THROTTLED = ("Too many wrong passwords — the server paused logins for a few "
             "minutes. Wait a little and try again.")


class ApiError(Exception):
    """Невдача запиту до API — з текстом для людини.

    code — HTTP-код (None, якщо до сервера не достукались), detail — що
    сказав сам сервер (для 404 це, наприклад, «preview is being prepared»).
    """

    def __init__(self, human, code=None, detail=""):
        super().__init__(human)
        self.code = code
        self.detail = detail or ""


class Where:
    """Де шукати API проєкту."""

    def __init__(self, origin, prefix, repo):
        self.origin = origin                  # https://host[:port]
        self.repo = repo                      # ім'я репозиторію
        self.api = origin + prefix + "/api/v1/"
        self.web = origin + prefix + "/browse/"

    def __repr__(self):
        return "Where(%r, %r)" % (self.api, self.repo)


def locate(root_url):
    """URL кореня репозиторію -> Where, або None, якщо це не svn-native.

    https://svn.studio/svn/demo      -> API https://svn.studio/api/v1/, repo demo
    https://h/tools/svn/demo         -> API https://h/tools/api/v1/  (сайт у підтеці)
    svn://h/demo, https://h/repos/x  -> None: такої розкладки ніхто не обіцяв
    """
    try:
        u = urllib.parse.urlsplit(root_url or "")
        port = u.port
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2 or parts[-2] != "svn":
        return None
    host = u.hostname
    if ":" in host:                          # IPv6 — у квадратних дужках
        host = "[%s]" % host
    # Будуємо з hostname і port, а не з netloc: у netloc можуть сидіти
    # user:password@, і тоді вони поїхали б у кожне посилання далі.
    origin = "%s://%s%s" % (u.scheme, host, (":%d" % port) if port else "")
    prefix = "".join("/" + p for p in parts[:-2])
    return Where(origin, prefix, urllib.parse.unquote(parts[-1]))


def repo_path(prefix, local):
    """Шлях у робочій копії -> шлях від кореня репозиторію.

    prefix — тека сховища, з якої знято копію ('' або '/trunk').
    """
    local = (local or "").replace("\\", "/").strip("/")
    base = (prefix or "").rstrip("/")
    return (base + "/" + local) if local else (base or "/")


def local_path(prefix, repo):
    """Шлях від кореня репозиторію -> шлях у копії, або None, якщо він поза нею."""
    base = (prefix or "").rstrip("/")
    repo = "/" + (repo or "").strip("/")
    if not base:
        return repo.strip("/")
    if repo == base:
        return ""
    if repo.startswith(base + "/"):
        return repo[len(base) + 1:]
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редирект — помилка, а не порада. Див. шапку модуля: пароль іде слідом."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _error_of(e):
    """HTTPError -> ApiError з тим, що сервер сам сказав."""
    said = ""
    try:
        body = e.read(65536)
        said = str(json.loads(body.decode("utf-8")).get("error") or "")
    except Exception:
        pass
    code = e.code
    if code == 401:
        return ApiError(AUTH, code, said)
    if code == 429:
        return ApiError(THROTTLED, code, said)
    if code == 403:
        # 403 від API задач — це правило, і сервер пояснює його сам
        # («Moving to Done is up to a supervisor.»): переказувати нема чого.
        return ApiError(said or "The server did not allow this.", code, said)
    if code == 404:
        return ApiError(said or "Not found on the server.", code, said)
    if 300 <= code < 400:
        return ApiError("The server tried to send APSVN somewhere else — it "
                        "does not follow that.", code, said)
    if code >= 500:
        return ApiError("The server had a problem answering. Try again in a "
                        "minute.", code, said)
    return ApiError(said or "The server refused the request (%d)." % code,
                    code, said)


def data_uri(raw, ctype):
    """Байти картинки -> data:URI, або None, якщо це не та картинка."""
    ctype = (ctype or "").split(";")[0].strip().lower()
    if not raw or ctype not in _IMAGE_TYPES:
        return None
    return "data:%s;base64,%s" % (ctype, base64.b64encode(raw).decode("ascii"))


class Client:
    """Запити до API одного сервера від імені однієї людини.

    Логін іде в КОЖНОМУ запиті (Basic), а не після виклику 401: так удвічі
    менше запитів, а сервер однаково пам'ятає вдалу перевірку 5 хвилин.
    """

    def __init__(self, where, username, password, timeout=TIMEOUT):
        self.where = where
        self.user = username or ""
        self.timeout = timeout
        pair = ("%s:%s" % (username or "", password or "")).encode("utf-8")
        self._auth = "Basic " + base64.b64encode(pair).decode("ascii")

    # --- транспорт --------------------------------------------------------
    def _same_origin(self, url):
        try:
            u = urllib.parse.urlsplit(url)
            port = u.port
        except ValueError:
            return False
        host = u.hostname or ""
        if ":" in host:
            host = "[%s]" % host
        return ("%s://%s%s" % (u.scheme, host, (":%d" % port) if port else "")
                == self.where.origin)

    def _open(self, method, url, body=None, image=False):
        if not self._same_origin(url):
            # Посилання прийшло у відповіді сервера. Навіть якщо сервер
            # помилився, логін іде лише туди, звідки ми його й узяли.
            raise ApiError("The server pointed APSVN to a different address — "
                           "it does not follow that.", None, url)
        headers = {"Authorization": self._auth, "User-Agent": "APSVN",
                   "Accept": "image/*" if image else "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        cap = MAX_IMAGE if image else MAX_JSON
        try:
            with _OPENER.open(req, timeout=self.timeout) as r:
                raw = r.read(cap + 1)
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise _error_of(e)
        except (urllib.error.URLError, OSError, ValueError) as e:
            # socket.timeout і ssl.SSLError — теж OSError
            raise ApiError(OFFLINE, None, str(e)[:200])
        if len(raw) > cap:
            raise ApiError("The server sent much more than expected.", None)
        if image:
            return raw, ctype
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ApiError("The server answered with something that is not "
                           "data — maybe it is not the studio server.", None,
                           raw[:200].decode("utf-8", "replace"))

    def _endpoint(self, endpoint, params=None):
        url = self.where.api + endpoint
        q = [(k, v) for k, v in (params or {}).items()
             if v is not None and v != "" and v is not False]
        if q:
            url += "?" + urllib.parse.urlencode(
                [(k, 1 if v is True else v) for k, v in q])
        return url

    def get(self, endpoint, params=None):
        return self._open("GET", self._endpoint(endpoint, params))

    def post(self, endpoint, body):
        return self._open("POST", self._endpoint(endpoint), body=body)

    def _repo(self, tail, params=None):
        return self.get("repos/%s/%s" % (urllib.parse.quote(self.where.repo,
                                                              safe=""), tail),
                        params)

    # --- що вміє сервер --------------------------------------------------
    def hello(self):
        """{'api':1, 'user', 'admin', 'endpoints': [...]}"""
        return self.get("")

    # --- задачі -----------------------------------------------------------
    def tasks(self, mine=False, status=None, inside=None, all_repos=False):
        return self.get("tasks", {
            "repo": None if all_repos else self.where.repo,
            "mine": "1" if mine else None,
            "status": ",".join(status) if status else None,
            "in": inside})

    def task(self, task_id):
        return self.get("tasks/%d" % int(task_id))

    def set_status(self, task_id, status, comment=""):
        return self.post("tasks/%d/status" % int(task_id),
                         {"status": status, "comment": comment or ""})

    def comment(self, task_id, text):
        return self.post("tasks/%d/comments" % int(task_id), {"text": text})

    # --- процеси й шоти (фаза 4) -----------------------------------------
    def processes(self):
        """Рецепти шотів: кроки по черзі (Blocking → Animation → Assembly)."""
        return self.get("processes")

    def shots(self):
        """Шоти проєкту: тека, процес, задачі за кроками, яких кроків бракує."""
        return self._repo("shots")

    # --- файли ------------------------------------------------------------
    def versions(self, path, limit=40):
        return self._repo("versions", {"path": path, "limit": limit})

    def deps(self, path, rev=None, recursive=False):
        return self._repo("deps", {"path": path, "rev": rev,
                                   "recursive": "1" if recursive else None})

    def usedby(self, path):
        return self._repo("usedby", {"path": path})

    def preview(self, path, rev=None):
        """Картинка файлу за шляхом і ревізією: (байти, тип) або None.

        None — картинки немає або ще немає («preview is being prepared»):
        для інтерфейсу це одне й те саме, місце лишається порожнім.
        """
        url = self._endpoint("repos/%s/preview" % urllib.parse.quote(
            self.where.repo, safe=""), {"path": path, "rev": rev})
        try:
            return self._open("GET", url, image=True)
        except ApiError as e:
            if e.code == 404:
                return None
            raise

    def blob(self, link):
        """Картинка за підписаним посиланням з відповіді (відносним)."""
        url = urllib.parse.urljoin(self.where.origin + "/", link or "")
        try:
            return self._open("GET", url, image=True)
        except ApiError as e:
            if e.code == 404:
                return None
            raise


class ImageCache:
    """Готові data:URI, обмежені за обсягом, а не за кількістю.

    Прев'ю файлу на конкретній ревізії не змінюється ніколи — сервер і сам
    віддає їх як immutable, — тож тримаємо, доки не впремося в стелю, і
    викидаємо найдавніше. Без стелі за обсягом довга сесія в History
    потроху з'їла б пам'ять: мініатюри .blend бувають і по 200 КБ.
    """

    def __init__(self, budget=32 << 20):
        self.budget = budget
        self.size = 0
        self._d = collections.OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self._d:
                return None
            self._d.move_to_end(key)
            return self._d[key]

    def has(self, key):
        with self._lock:
            return key in self._d

    def put(self, key, value):
        cost = len(value or "") + 64
        with self._lock:
            if key in self._d:
                self.size -= len(self._d[key] or "") + 64
            self._d[key] = value
            self._d.move_to_end(key)
            self.size += cost
            while self.size > self.budget and len(self._d) > 1:
                _, old = self._d.popitem(last=False)
                self.size -= len(old or "") + 64


def fetch_all(fn, items, workers=WORKERS):
    """fn(item) для кожного — паралельно, але не більше workers одночасно.

    Невдача одного не зупиняє решту: порожнє місце замість однієї картинки
    краще, ніж жодної.
    """
    items = list(items)
    if not items:
        return []

    def safe(it):
        try:
            return fn(it)
        except Exception:
            return None

    if len(items) == 1:
        return [safe(items[0])]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(safe, items))


def content_key(path, chunk=1 << 20):
    """'s' + SHA-1 вмісту файлу — у тій самій формі, що ключі версій на сервері.

    Так видно, яка з версій лежить у людини на диску, нічого не завантажуючи.
    """
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return "s" + h.hexdigest()


def covering(tasks, local):
    """Задачі, що накривають файл: на ньому самому або на теці над ним.

    Задача на теці сервер рахує задачею на все під нею (так працює і м'який
    лок), тож і тут так само. Найближча — першою: задача на самому файлі
    каже про нього більше, ніж задача на теці шота.
    """
    local = (local or "").strip("/")
    out = []
    for t in tasks:
        tp = t.get("local")
        if tp is None:
            continue
        tp = tp.strip("/")
        if tp == local or tp == "" or local.startswith(tp + "/"):
            out.append(t)
    out.sort(key=lambda t: -len((t.get("local") or "").strip("/")))
    return out


# Посилання сервера на задачу в Kitsu: <база>/productions/<id>/<assets|shots>/tasks/<id>.
# Адресу Kitsu APSVN більше ніде не бере: сервер її знає (публічну, з панелі),
# а в /v1/ окремо не віддає. Тому все, що веде в Kitsu, складається з цих
# посилань — і лише з тих, що мають саме таку форму.
_KITSU_TASK = re.compile(
    r"^(https?://[^/?#\s]+(?:/[^?#\s]*?)?)/productions/([A-Za-z0-9-]{1,64})/"
    r"(assets|shots|edits|sequences|episodes)/tasks/([A-Za-z0-9-]{1,64})/?$")


def kitsu_task(url):
    """Сторінка задачі в Kitsu -> (база, постановка, вид, задача) або None."""
    m = _KITSU_TASK.match(str(url or "").strip())
    return m.groups() if m else None


def kitsu_links(tasks):
    """Адреси в Kitsu, складені з посилань на задачі; None — жодного немає.

    mine — «My Tasks» людини в усіх постановках; board — сторінка постановки
    цього проєкту: шоти, якщо вони в ній є, інакше ассети. Шляхи звірено з
    маршрутизатором Kitsu студії (2026-09-25): «My Tasks» — /my-tasks (у
    старших версіях Kitsu було /todos, тепер його там немає).
    """
    by_task, bases, prods, kinds = {}, [], [], set()
    for t in tasks:
        got = kitsu_task(t.get("url"))
        if not got:
            continue
        base, prod, kind, _ = got
        by_task[t.get("id")] = "%s/productions/%s/%s/tasks/%s" % got
        bases.append(base)
        prods.append(prod)
        kinds.add(kind)
    if not by_task:
        return None
    base = max(set(bases), key=bases.count)
    prod = max(set(prods), key=prods.count)
    page = "shots" if "shots" in kinds else "assets"
    return {"base": base, "mine": base + "/my-tasks",
            "board": "%s/productions/%s/%s" % (base, prod, page), "tasks": by_task}


def waiting(t):
    """Задача, до якої ще не дійшла черга: у To do, а попередній крок шоту
    керівник ще не прийняв. Сервер її не рахує в «My tasks», рухати її
    художник не може (403), перший коміт її не починає."""
    return t.get("status") == "todo" and bool(t.get("waiting_for"))


def owners(tasks, local):
    """(люди, задачі) — чий зараз файл. ДЗЕРКАЛО tracker.owners на сервері.

    Правило те саме, за яким вирішує хук м'якого локу, і тримати його треба
    в згоді з сервером: розбіжність означала б позначку «вільний» у списку, а
    потім відмову хука (або навпаки — «чужий» файл, який насправді можна):
      * вирішує НАЙБЛИЖЧИЙ рівень: задача на самому файлі важливіша за задачу
        на теці шоту над ним — навіть уже прийнята; тоді файл просто нічий.
        Тому tasks мусять містити й завершені задачі;
      * на цьому рівні — кроки, до яких дійшла черга (Blocking, а не
        Animation, що чекає на нього); якщо чекають усі — усі незавершені.
    Порожній набір людей означає, що файл може здати будь-хто.
    """
    cover = covering(tasks, local)                 # найглибші — першими
    if not cover:
        return set(), []
    deepest = len((cover[0].get("local") or "").strip("/"))
    level = [t for t in cover
             if len((t.get("local") or "").strip("/")) == deepest
             and t.get("status") != "done"]
    current = [t for t in level if not t.get("waiting_for")] or level
    people = set()
    for t in current:
        people.update(t.get("assignees") or [])
    return people, current
