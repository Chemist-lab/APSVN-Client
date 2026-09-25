# -*- coding: utf-8 -*-
"""Сервер студії: прев'ю, залежності, задачі — і відмова м'якого локу.

Справжній сервер (svn-native) тут не потрібен і не чіпається: поруч
піднімається підробний, який відповідає тими самими формами, що й
admin/api_app.py, — і рівно так само відмовляє. Живий сервер перевіряє
test_live.py, лише читанням.

Що тут доводиться, а не припускається:
* логін не йде туди, куди сервер «перенаправив», і за абсолютним посиланням
  з відповіді — другий сервер-пастка рахує, чи до нього хтось прийшов;
* відмова хука доходить до людини тим самим текстом, який написав сервер, —
  на справжньому svn зі справжніми хуками, а не на вигаданому рядку;
* задачі лягають на файли копії, знятої з підтеки (/trunk), і задача на теці
  накриває все під нею, але не сусідню теку з тим самим початком імені.
"""
import base64
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "app"))
import svn_client as sc
import server_api as srv
import imgthumb
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" | " + str(detail) if detail else ""))


BASE = tempfile.mkdtemp(prefix="apsvn_srv_")
app.CONF_DIR = os.path.join(BASE, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.LOG = os.path.join(app.CONF_DIR, "error.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")


class FakeKeyring:
    def __init__(self):
        self.d = {}

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def get_password(self, s, u):
        return self.d.get((s, u))


app.keyring = FakeKeyring()


def png(r, g, b):
    return imgthumb.encode_png(2, 2, bytes([r, g, b]) * 4)


# ---------------------------------------------------------------- 1. адреси
print("--- де шукати API ---")
w = srv.locate("https://svn.altpicture.cloud/svn/demo")
check("svn-native: /svn/<repo> -> /api/v1/",
      w and w.api == "https://svn.altpicture.cloud/api/v1/" and w.repo == "demo",
      w)
check("сайт — /browse/", w and w.web == "https://svn.altpicture.cloud/browse/")
w = srv.locate("https://h.example:8443/tools/svn/%D0%BF%D1%80%D0%BE%D1%94%D0%BA%D1%82")
check("сайт у підтеці й нестандартний порт",
      w and w.api == "https://h.example:8443/tools/api/v1/", w)
check("кириличне ім'я репозиторію розкодовано", w and w.repo == "проєкт", w and w.repo)
w = srv.locate("https://anya:secret@svn.example/svn/demo")
check("логін з адреси не потрапляє в посилання API",
      w and "secret" not in w.api and "anya" not in w.origin, w and w.api)
check("svn:// — не svn-native", srv.locate("svn://host/demo") is None)
check("інша розкладка — не шукаємо", srv.locate("https://host/repos/demo") is None)
check("file:// — не шукаємо", srv.locate("file:///C:/repo") is None)
check("сміття — None, без винятку", srv.locate("https://host:99999/svn/x") is None)

print("--- шляхи копії й сховища ---")
check("копія з /trunk: файл -> шлях сховища",
      srv.repo_path("/trunk", "Shots/sh010.blend") == "/trunk/Shots/sh010.blend")
check("копія з кореня", srv.repo_path("", "Shots/a.blend") == "/Shots/a.blend")
check("корінь копії", srv.repo_path("/trunk", "") == "/trunk")
check("назад: сховище -> копія",
      srv.local_path("/trunk", "/trunk/Shots/sh010.blend") == "Shots/sh010.blend")
check("поза копією — None", srv.local_path("/trunk", "/branches/x.blend") is None)
check("сусід із тим самим початком — теж поза копією",
      srv.local_path("/trunk", "/trunk2/x.blend") is None)
check("сама тека копії — ''", srv.local_path("/trunk", "/trunk") == "")
check("копія з кореня: шлях без першого слеша",
      srv.local_path("", "/Кадри/сцена.blend") == "Кадри/сцена.blend")

print("--- які задачі накривають файл ---")
T = [{"id": 1, "local": "Shots/sh010.blend"},
     {"id": 2, "local": "Shots"},
     {"id": 3, "local": "Shots/sh01"},
     {"id": 4, "local": None}]
got = [t["id"] for t in srv.covering(T, "Shots/sh010.blend")]
check("задача на файлі й на теці над ним — найближча першою", got == [1, 2], got)
check("тека sh01 не накриває sh010.blend", 3 not in got, got)
check("задача поза копією не накриває нічого", 4 not in got)
check("задача на корені копії накриває все",
      [t["id"] for t in srv.covering([{"id": 9, "local": ""}], "a/b.png")] == [9])

print("--- кеш картинок тримає стелю за обсягом ---")
cache = srv.ImageCache(budget=1000)
for i in range(20):
    cache.put(i, "x" * 200)
check("старе викинуто, обсяг у межах", cache.size <= 1000 and not cache.has(0)
      and cache.has(19), cache.size)
check("SVG не стає картинкою інтерфейсу",
      srv.data_uri(b"<svg onload=alert(1)>", "image/svg+xml") is None)
check("PNG стає data:URI",
      (srv.data_uri(png(1, 2, 3), "image/png") or "").startswith("data:image/png;base64,"))


# --------------------------------------------------------- 2. підробний сервер
USER, PASSWORD = "olena", "пароль-1"
EXPECT = "Basic " + base64.b64encode(("%s:%s" % (USER, PASSWORD)).encode("utf-8")).decode()

CONTENT = {25: b"scene version 25", 24: b"scene version 24", 18: b"scene v18"}
KEYS = {r: "s" + hashlib.sha1(c).hexdigest() for r, c in CONTENT.items()}
BLOBS = {KEYS[25]: png(250, 0, 0), KEYS[24]: png(0, 240, 0)}
PREVIEWS = {("/trunk/Shots/sh010.blend", 25): png(10, 20, 30),
            ("/trunk/Shots/sh010.blend", None): png(10, 20, 31),
            ("/trunk/tex/wood.png", 7): png(40, 50, 60)}

TASKS = {
    11: {"id": 11, "repo": "demo", "path": "/trunk/Shots/sh010.blend",
         "type": "Animation", "title": "", "status": "todo", "due": "2026-10-01",
         "assignees": ["olena"], "created_by": "andrii", "gone": 0,
         "status_name": "To do", "overdue": False, "name": "sh010.blend",
         "created": 1, "updated": 5},
    12: {"id": 12, "repo": "demo", "path": "/trunk/Shots/sh020",
         "type": "Lighting", "title": "sh020 light", "status": "wip", "due": None,
         "assignees": ["taras"], "created_by": "andrii", "gone": 0,
         "status_name": "In progress", "overdue": False, "name": "sh020 light",
         "created": 1, "updated": 4},
    13: {"id": 13, "repo": "demo", "path": "/branches/old.blend",
         "type": "FX", "title": "", "status": "retake", "due": "2020-01-01",
         "assignees": ["olena"], "created_by": "andrii", "gone": 0,
         "status_name": "Retake", "overdue": True, "name": "old.blend",
         "created": 1, "updated": 3},
    14: {"id": 14, "repo": "demo", "path": "/trunk/Shots/sh030.blend",
         "type": "Animation", "title": "", "status": "done", "due": None,
         "assignees": ["olena"], "created_by": "andrii", "gone": 0,
         "status_name": "Done", "overdue": False, "name": "sh030.blend",
         "created": 1, "updated": 2},
}
# Фаза 4: шот sh040 процесу Shot. На одному файлі два кроки: Blocking (taras,
# на перевірці) і Animation (olena), що чекає, поки Blocking приймуть. Над ними
# — задача на теці шоту (andrii). notes.txt має власну, уже прийняту задачу —
# і тому, за правилом сервера, нічий, хоч над ним і висить задача теки.
def _t(i, path, typ, status, who, entity=None, step=None, waiting=()):
    return {"id": i, "repo": "demo", "path": path, "type": typ, "title": "",
            "status": status, "due": None, "assignees": list(who),
            "created_by": "andrii", "gone": 0,
            "status_name": srv.STATUS_NAMES.get(status, status), "overdue": False,
            "name": path.rsplit("/", 1)[-1], "created": 1, "updated": 1,
            "entity": entity, "step": step, "waiting_for": list(waiting)}


TASKS.update({
    15: _t(15, "/trunk/Shots/sh040/sh040_anim.blend", "Blocking", "wfa", ["taras"], 7, 1),
    16: _t(16, "/trunk/Shots/sh040/sh040_anim.blend", "Animation", "todo", ["olena"], 7, 2,
           ["Blocking"]),
    17: _t(17, "/trunk/Shots/sh040", "Layout", "wip", ["andrii"], 7),
    18: _t(18, "/trunk/Shots/sh040/notes.txt", "Notes", "done", ["taras"], 7),
})
# Задачі з Kitsu: чужа (дивитися можна, змінювати — ні), своя зі статусом, якого
# в нас немає (Ready), і чужа, яку бачить керівник.
TASKS.update({
    31: dict(_t(31, "/trunk/Assets/prop/lamp", "Modeling", "wip", ["taras"]), kitsu=True),
    32: dict(_t(32, "/trunk/Assets/prop/chair", "Modeling", "ready", ["olena"]),
             kitsu=True, status_name="Ready To Start"),
    33: dict(_t(33, "/trunk/Assets/prop/table", "Rigging", "wfa", ["taras"]), kitsu=True,
             lead=True),
    34: dict(_t(34, "/trunk/Assets/prop/sofa", "Rigging", "wip", ["taras"]), kitsu=True,
             linked=False),
})
KITSU_MOVES = {32: [{"key": "wip", "name": "Work In Progress"},
                    {"key": "wfa", "name": "Waiting For Approval"}],
               33: [{"key": "done", "name": "Done"}, {"key": "retake", "name": "Retake"},
                    {"key": "approved", "name": "Approved"}]}
PROCESSES = [{"id": 1, "name": "Shot", "kind": "shot", "steps": [
    {"id": 1, "name": "Blocking"}, {"id": 2, "name": "Animation"},
    {"id": 3, "name": "Assembly"}]}]
EVENTS = {11: [{"at": 100, "user": "andrii", "kind": "created", "old": None,
                "new": "olena", "comment": None, "rev": None}]}
MOVES = srv.ARTIST_MOVES


class Handler(http.server.BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _route(self, method):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        auth = self.headers.get("Authorization")
        Handler.hits.append((method, u.path, auth))
        if u.path == "/api/v1/notjson":
            return self._send(200, b"<html>login page</html>", "text/html")
        if auth and auth.startswith("Basic ") and base64.b64decode(
                auth[6:]).decode("utf-8", "replace").startswith("flood:"):
            return self._send(429, {"error": "too many attempts"})
        if auth != EXPECT:
            return self._send(401, {"error": "authentication required"},
                              extra={"WWW-Authenticate": 'Basic realm="x"'})
        p = u.path
        if p == "/api/v1/redirect":
            return self._send(302, {"error": "moved"},
                              extra={"Location": TRAP + "/steal"})
        if p == "/api/v1/":
            return self._send(200, {"api": 1, "user": USER, "admin": False,
                                    "endpoints": ["/api/v1/repos",
                                                  "/api/v1/tasks",
                                                  "/api/v1/tasks/<id>",
                                                  "/api/v1/processes",
                                                  "/api/v1/repos/<repo>/shots"]})
        if p == "/api/v1/tasks" and method == "GET":
            out = list(TASKS.values())
            if q.get("repo"):
                out = [t for t in out if t["repo"] == q["repo"]]
            if q.get("mine"):
                out = [t for t in out if USER in t["assignees"]]
            if q.get("status"):
                want = q["status"].split(",")
                out = [t for t in out if t["status"] in want]
            return self._send(200, {"tasks": out, "statuses": []})
        if p.startswith("/api/v1/tasks/"):
            parts = p.split("/")
            tid = int(parts[4])
            t = TASKS.get(tid)
            if t is None:
                return self._send(404, {"error": "not found"})
            if len(parts) == 5:
                if t.get("kitsu"):
                    # як сервер із Kitsu: сам каже, що ЦІЙ людині можна
                    return self._send(200, {"task": dict(t, events=[], moves=KITSU_MOVES.get(
                        tid, [])), "supervisor": t.get("lead", False),
                        "linked": t.get("linked", True)})
                return self._send(200, {"task": dict(t, events=EVENTS.get(tid, [])),
                                        "supervisor": False})
            body = json.loads(self.rfile.read(int(self.headers.get(
                "Content-Length") or 0)).decode("utf-8") or "{}")
            if parts[5] == "status" and t.get("kitsu"):
                new = body.get("status")
                allowed = [m["key"] for m in KITSU_MOVES.get(tid, [])]
                if new not in allowed:
                    return self._send(403, {"error": "Only the assignee or a supervisor "
                                            "can set this here."})
                t.update(status=new, status_name={m["key"]: m["name"] for m in
                                                  KITSU_MOVES[tid]}[new])
                return self._send(200, {"task": t})
            if parts[5] == "status":
                new = body.get("status")
                if USER not in t["assignees"]:
                    return self._send(403, {"error": "Only the assignee or a "
                                            "supervisor can change this task."})
                if (t["status"], new) not in MOVES:
                    return self._send(403, {"error": "Moving to %s is up to a "
                                            "supervisor." % srv.STATUS_NAMES.get(new, new)})
                EVENTS.setdefault(tid, []).append(
                    {"at": 200, "user": USER, "kind": "status", "old": t["status"],
                     "new": new, "comment": body.get("comment"), "rev": None})
                t.update(status=new, status_name=srv.STATUS_NAMES[new])
                return self._send(200, {"task": t})
            if parts[5] == "comments":
                EVENTS.setdefault(tid, []).append(
                    {"at": 300, "user": USER, "kind": "comment", "old": None,
                     "new": None, "comment": body.get("text"), "rev": None})
                return self._send(200, {"ok": True})
        if p == "/api/v1/processes":
            return self._send(200, {"processes": PROCESSES, "modes": ["new", "same", "none"]})
        if p == "/api/v1/repos/demo/shots":
            # задачі навмисно не в порядку кроків — порядок має дати процес
            return self._send(200, {"repo": "demo", "shots": [{
                "id": 7, "name": "sh040", "group": "sq010", "kind": "shot",
                "folder": "/trunk/Shots/sh040", "process": "Shot",
                "missing_steps": ["Assembly"],
                "tasks": [TASKS[16], TASKS[17], TASKS[15]]}]})
        if p == "/api/v1/repos/demo/preview":
            rev = int(q["rev"]) if q.get("rev") else None
            img = PREVIEWS.get((q.get("path"), rev))
            if img is None:
                return self._send(404, {"error": "preview is being prepared"})
            return self._send(200, img, "image/png")
        if p == "/api/v1/repos/demo/versions":
            vs = []
            for rev in (25, 24, 18):
                pv = {"state": "ok", "key": KEYS[rev],
                      "url": "/api/v1/blobs/%s?s=sig-%s" % (KEYS[rev], KEYS[rev][:6])}
                if rev == 18:
                    pv = {"state": "pending", "key": KEYS[rev]}
                vs.append({"rev": rev, "path": q.get("path"), "key": KEYS[rev],
                           "author": "olena", "msg": "v%d" % rev, "preview": pv})
            return self._send(200, {"versions": vs})
        if p.startswith("/api/v1/blobs/"):
            key = p.rsplit("/", 1)[-1]
            if q.get("s") != "sig-" + key[:6] or key not in BLOBS:
                return self._send(404, {"error": "not found"})
            return self._send(200, BLOBS[key], "image/png")
        if p == "/api/v1/repos/demo/deps":
            links = ([{"kind": "image", "raw": "//tex/wood.png", "name": "wood",
                       "state": "ok", "target": "/trunk/tex/wood.png"},
                      {"kind": "image", "raw": "//tex/gone.png", "name": "gone",
                       "state": "missing", "target": "/trunk/tex/gone.png"},
                      {"kind": "library", "raw": "C:/Users/me/rig.blend",
                       "name": "rig", "state": "absolute", "target": "/trunk/rig.blend"},
                      {"kind": "volume", "raw": "X:/cache/smoke_####.vdb",
                       "name": "smoke", "state": "external", "target": None}]
                     + [{"kind": "image", "raw": "p%d.png" % i, "name": "p%d" % i,
                         "state": "packed", "target": None} for i in range(30)])
            return self._send(200, {"state": "ok", "blender": "4.2", "links": links,
                                    "closure": {"files": [
                                        {"path": "/trunk/tex/wood.png"},
                                        {"path": "/trunk/rig.blend"}],
                                        "pending": [], "problems": 2}})
        if p == "/api/v1/repos/demo/usedby":
            users = {"/trunk/tex/wood.png": ["/trunk/Shots/sh010.blend",
                                             "/trunk/Shots/sh020.blend"],
                     "/trunk/rig.blend": ["/trunk/Shots/sh010.blend"]}.get(q.get("path"), [])
            return self._send(200, {"complete": True,
                                    "users": [{"source": s, "state": "ok"} for s in users]})
        return self._send(404, {"error": "not found"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


class Trap(http.server.BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Trap.hits.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")


def serve(handler):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


server, trap = serve(Handler), serve(Trap)
HOST = "http://127.0.0.1:%d" % server.server_address[1]
TRAP = "http://127.0.0.1:%d" % trap.server_address[1]
where = srv.locate(HOST + "/svn/demo")
client = srv.Client(where, USER, PASSWORD)

print("--- клієнт: вхід і відмови ---")
h = client.hello()
check("вхід Basic із кириличним паролем", h.get("user") == USER, h)
try:
    srv.Client(where, USER, "wrong").hello()
    check("хибний пароль — відмова", False)
except srv.ApiError as e:
    check("хибний пароль: код 401 і людський текст",
          e.code == 401 and "user name or password" in str(e), e)
try:
    srv.Client(where, "flood", "x").hello()
    check("429 пояснено", False)
except srv.ApiError as e:
    check("429: «зачекай кілька хвилин», а не «помилка»",
          e.code == 429 and "few minutes" in str(e), e)
try:
    client.get("redirect")
    check("редирект — помилка", False)
except srv.ApiError as e:
    check("редирект не виконується", e.code == 302, e)
check("за редиректом логін нікуди не пішов", Trap.hits == [], Trap.hits)
try:
    client.blob(TRAP + "/stolen.png")
    check("абсолютне посилання на чужий хост відхилено", False)
except srv.ApiError as e:
    check("абсолютне посилання на чужий хост відхилено", "different address" in str(e), e)
check("до пастки не прийшов жоден запит", Trap.hits == [], Trap.hits)
try:
    client.get("notjson")
    check("не-JSON — помилка", False)
except srv.ApiError as e:
    check("сторінка входу замість даних не стає даними", "not data" in str(e), e)
dead = srv.Client(srv.locate("http://127.0.0.1:1/svn/demo"), USER, PASSWORD, timeout=3)
try:
    dead.hello()
    check("немає сервера — помилка", False)
except srv.ApiError as e:
    check("немає сервера: «немає зв'язку», код None", e.code is None and
          str(e) == srv.OFFLINE, e)

print("--- клієнт: задачі ---")
t = client.tasks(status=srv.ACTIVE)
check("активні задачі проєкту", sorted(x["id"] for x in t["tasks"]) == [11, 12, 13, 15, 16, 17, 31, 33, 34],
      [x["id"] for x in t["tasks"]])
try:
    client.set_status(12, "wfa")
    check("чужу задачу рухати не можна", False)
except srv.ApiError as e:
    check("чужа задача: 403 з поясненням сервера",
          e.code == 403 and "assignee" in str(e), e)
try:
    client.set_status(11, "done")
    check("прийняти може лише керівник", False)
except srv.ApiError as e:
    check("done: 403 «up to a supervisor» — текст сервера як є",
          e.code == 403 and str(e) == "Moving to Done is up to a supervisor.", e)
check("кириличний коментар до зміни статусу доходить",
      client.set_status(11, "wip", "почала")["task"]["status"] == "wip"
      and EVENTS[11][-1]["comment"] == "почала", EVENTS[11][-1])

print("--- клієнт: картинки ---")
got = client.preview("/trunk/Shots/sh010.blend", 25)
check("прев'ю на ревізії — PNG", got and got[0] == PREVIEWS[("/trunk/Shots/sh010.blend", 25)]
      and got[1] == "image/png")
check("«готується» — None, а не помилка", client.preview("/trunk/nope.blend", 3) is None)
got = client.blob("/api/v1/blobs/%s?s=sig-%s" % (KEYS[25], KEYS[25][:6]))
check("підписане відносне посилання качається", got and got[0] == BLOBS[KEYS[25]])


# ------------------------------------------------------------- 3. шар Api
print("--- Api: задачі в копії, знятій з /trunk ---")
wc = os.path.join(BASE, "копія")
os.makedirs(os.path.join(wc, "Shots", "sh020"))
os.makedirs(os.path.join(wc, "tex"))
with open(os.path.join(wc, "Shots", "sh010.blend"), "wb") as fh:
    fh.write(CONTENT[24])                          # у людини — версія 24
api = app.Api()
api.conf = {"format": 2, "current": "p1", "projects": [
    {"id": "p1", "name": "demo", "wc": wc, "url": HOST + "/svn/demo/trunk",
     "username": USER}]}
app.keyring.set_password("APSVN", "proj:p1", PASSWORD)
api._last["p1"] = {"info": {"root": HOST + "/svn/demo",
                            "url": HOST + "/svn/demo/trunk", "revision": "30"},
                   "files": [{"path": "tex/wood.png", "remote_change": True},
                             {"path": "Shots/sh010.blend", "status": "modified"}]}

s = api.server_status()
check("сервер знайдено за адресою проєкту", s.get("ok") and s.get("tasks")
      and s.get("me") == USER, s)
n0 = len(Handler.hits)
api.server_status()
check("відповідь сервера пам'ятається — другий раз без запиту",
      len(Handler.hits) == n0)

ov = api.tasks_overview(force=True)
by = {t["id"]: t for t in ov.get("tasks", [])}
check("прочитано ВСІ задачі — і завершені (їх потребує правило «чий файл»)",
      ov.get("ok") and set(by) == {11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34}, ov.get("error"))
check("шлях задачі переведено в шлях копії",
      by[11]["local"] == "Shots/sh010.blend", by[11]["local"])
check("задача поза копією (гілка) — local None", by[13]["local"] is None)
check("своя / чужа", by[11]["mine"] and not by[12]["mine"])
check("задача на теці впізнана як тека", by[12]["is_dir"] is True)
check("файл задачі на диску", by[11]["on_disk"] is True)
check("у роботі виконавцю можна лише на перевірку", by[11]["moves"] == ["wfa"],
      by[11]["moves"])
check("чужій задачі кнопок не дають", by[12]["moves"] == [])
check("retake -> робота або перевірка", by[13]["moves"] == ["wip", "wfa"], by[13]["moves"])

why = api._assigned_elsewhere(["Shots/sh020/light.blend", "Shots/sh010.blend"], "lock")
check("пояснення «чий файл» — у формі хука й лише про чужий",
      why and "These files are assigned to someone else:" in why
      and "Shots/sh020/light.blend — taras (Lighting, In progress)" in why
      and "sh010" not in why, why)

print("--- фаза 4: черговість кроків і «чий файл» — як на сервері ---")
check("крок, що чекає на попередній, — «наступний», а не робота",
      by[16]["waiting"] is True and by[16]["waiting_for"] == ["Blocking"], by[16])
check("…і кнопок йому не дають (сервер відповів би 403)", by[16]["moves"] == [],
      by[16]["moves"])
check("крок, до якого дійшла черга, — звичайна задача",
      by[15]["waiting"] is False and by[15]["entity"] == 7 and by[15]["step"] == 1)
T = ov["tasks"]
people, cur = srv.owners(T, "Shots/sh040/sh040_anim.blend")
check("два кроки на файлі: вирішує той, до якого дійшла черга (Blocking — taras)",
      people == {"taras"} and [t["id"] for t in cur] == [15], (people, [t["id"] for t in cur]))
people, cur = srv.owners(T, "Shots/sh040/other.png")
check("файл без своєї задачі — задача теки шоту (andrii)", people == {"andrii"}, people)
people, cur = srv.owners(T, "Shots/sh040/notes.txt")
check("прийнята задача на самому файлі робить його нічиїм, хоч над ним задача теки",
      people == set() and cur == [], (people, cur))
only_waiting = [dict(by[16], local="x.blend"), dict(by[15], local="y.blend")]
people, cur = srv.owners(only_waiting, "x.blend")
check("якщо на рівні чекають усі — рахуються всі незавершені",
      people == {"olena"} and [t["id"] for t in cur] == [16], people)
two_now = [dict(by[15], local="z.blend"),
           dict(by[12], local="z.blend", type="Lighting", status="todo", status_name="To do",
                waiting_for=[])]
api._tasks["p1"]["out"]["tasks"].extend(two_now)
why = api._assigned_elsewhere(["z.blend"], "commit")
check("пояснення в новому форматі сервера: «шлях — люди (Тип, Статус; …)»",
      why and "  z.blend — taras (Blocking, Review; Lighting, To do)" in why, why)
del api._tasks["p1"]["out"]["tasks"][-2:]
sp = api.shot_pipeline(7)
check("шот задачі: кроки за порядком процесу, а не як прийшли",
      sp and [s_["step"] for s_ in sp["steps"]][:2] == ["Blocking", "Animation"], sp)
check("…крок без місця в процесі (задача теки) — наприкінці",
      sp and sp["steps"][-1]["task"]["id"] == 17, sp and [s_["task"]["id"] for s_ in sp["steps"]])
check("…свій крок позначено, і видно, на що він чекає",
      sp and sp["steps"][1]["task"]["mine"] and sp["steps"][1]["task"]["waiting"])
check("…кроки, яких шоту бракує, названо", sp and sp["missing"] == ["Assembly"], sp)
check("…тека шоту — у шляхах копії", sp and sp["folder"] == "Shots/sh040", sp)
check("шоту немає — None, без винятку", api.shot_pipeline(999) is None)
check("шаблони /templates поза копією з /trunk — не показуємо",
      api.server_status().get("templates") is None, api.server_status())

print("--- Api: відмова лока без тексту хука пояснюється задачею ---")
real_lock = sc.lock


def forbidden(*a, **kw):
    raise sc.SvnError("x", "svn: warning: W160039: Unexpected HTTP status 403 "
                           "'Forbidden' on '/svn/demo/!svn/me'")


def other_failure(*a, **kw):
    raise sc.SvnError("Somebody else has this file locked", "svn: W160035: "
                      "Path '/trunk/Shots/sh020/light.blend' is already locked "
                      "by user 'taras'")


sc.lock = forbidden
try:
    api.do_lock(["Shots/sh020/light.blend"])
    check("403 на чужому файлі -> RuleError", False)
except sc.RuleError as e:
    check("403 на чужому файлі -> RuleError з іменем виконавця", "taras" in str(e), e)
sc.lock = other_failure
try:
    api.do_lock(["Shots/sh020/light.blend"])
except sc.RuleError as e:
    check("звичайний чужий лок НЕ підміняється поясненням задачі", False, e)
except sc.SvnError as e:
    check("звичайний чужий лок НЕ підміняється поясненням задачі",
          "locked" in str(e), e)
sc.lock = real_lock

print("--- Api: кроки задачі ---")
try:
    api.task_move(12, "wfa")
    check("чужа задача -> RuleError", False)
except sc.RuleError as e:
    check("403 від задач стає вікном-поясненням (RuleError)", "assignee" in str(e), e)
msg = api._send_to_review([11], "анімація стрибка", "57")
check("після здачі — на перевірку, з приміткою коміту",
      "Sent to review" in msg and TASKS[11]["status"] == "wfa"
      and EVENTS[11][-1]["comment"] == "анімація стрибка\n(commit 57)", msg)
msg = api._send_to_review([12], "x", "58")
check("невдала зміна статусу не видає себе за невдалу здачу",
      "not sent to review" in msg and "Sent to review" not in msg, msg)
check("коментар", api.task_comment(11, "готово до перевірки") == "Comment added"
      and EVENTS[11][-1]["comment"] == "готово до перевірки")
d = api.task_detail(11)
check("задача зі стрічкою — новіші зверху", d["events"][0]["kind"] == "comment"
      and d["events"][-1]["kind"] == "created", [e["kind"] for e in d["events"]])
check("у задачі — картинка файлу", (d.get("preview") or "").startswith("data:image/png"))
done = api.tasks_done()
check("завершені — лише мої й лише на вимогу", [t["id"] for t in done] == [14],
      [t["id"] for t in done])

print("--- задачі всього проєкту: права з сервера (Kitsu) ---")
d = api.task_detail(31)
check("чужу задачу видно й відкрито — кнопок статусу немає (сервер не дав)",
      d["moves"] == [] and not d["mine"], d["moves"])
check("…коментувати чужу — ні (у Kitsu це виконавець або керівник)",
      d["can_comment"] is False)
d = api.task_detail(32)
check("своя задача зі статусом, якого в нас немає (Ready), — кроки від сервера",
      d["moves"] == ["wip", "wfa"] and d["move_names"]["wfa"] == "Waiting For Approval",
      d["moves"])
check("…і коментувати свою можна", d["can_comment"] is True)
d = api.task_detail(33)
check("керівник на чужій задачі — усе, що дав сервер, разом зі статусом Kitsu",
      d["supervisor"] and d["moves"] == ["done", "retake", "approved"]
      and d["can_comment"] is True, (d["supervisor"], d["moves"]))
msg = api.task_move(33, "approved", "гарно")
check("статус, якого в нас немає (approved), іде на сервер як є",
      "Approved" in msg and TASKS[33]["status"] == "approved", msg)
for junk in ("approved; rm", "", "a" * 60, "../x"):
    try:
        api.task_move(33, junk)
        check("сміття замість статусу не йде на сервер: %r" % junk[:12], False)
    except sc.SvnError:
        check("сміття замість статусу не йде на сервер: %r" % junk[:12], True)
d = api.task_detail(34)
check("не зіставлений із Kitsu — дивиться, але не змінює й не коментує",
      d["linked"] is False and d["can_comment"] is False, d["linked"])
d = api.task_detail(11)
check("старий сервер (без moves у задачі) — як і було: свої кроки, коментувати можна",
      d["can_comment"] is True and d["linked"] is True and d["move_names"] == {},
      (d["moves"], d["can_comment"]))

print("--- Api: прев'ю ---")
n0 = len(Handler.hits)
pv = api.previews([{"path": "Shots/sh010.blend", "rev": 25},
                   {"path": "Shots/sh010.blend", "rev": None},
                   {"path": "tex/wood.png", "rev": "7"},
                   {"path": "rig.fbx", "rev": 3},
                   {"path": "Shots/never.blend", "rev": 2}])
check("ключі «шлях@ревізія»", set(pv) == {"Shots/sh010.blend@25", "Shots/sh010.blend@",
                                         "tex/wood.png@7", "Shots/never.blend@2"}, sorted(pv))
check("картинки прийшли", all(pv[k] for k in ("Shots/sh010.blend@25",
                                              "Shots/sh010.blend@", "tex/wood.png@7")))
check("чого нема — None", pv["Shots/never.blend@2"] is None)
check(".fbx навіть не питали", not any("rig.fbx" in (h[1] or "") for h in Handler.hits[n0:]))
n1 = len(Handler.hits)
api.previews([{"path": "Shots/sh010.blend", "rev": 25}])
check("ревізія не змінюється — другий раз із пам'яті", len(Handler.hits) == n1)
api.previews([{"path": "Shots/never.blend", "rev": 2}])
check("«ще нема» не запам'ятовується — спитаємо знову", len(Handler.hits) == n1 + 1)

print("--- Api: версії файлу й «яка в тебе» ---")
v = api.file_versions("Shots/sh010.blend")
check("версії за ревізіями", v.get("ok") and set(v["versions"]) == {"25", "24", "18"},
      v)
check("картинки версій", v["versions"]["25"]["preview"] and v["versions"]["24"]["preview"])
check("«готується» лишається без картинки", v["versions"]["18"]["preview"] is None
      and v["versions"]["18"]["state"] == "pending")
check("у людини на диску — версія 24 (за SHA-1)",
      api.which_version("Shots/sh010.blend") == {"rev": 24},
      api.which_version("Shots/sh010.blend"))
with open(os.path.join(wc, "Shots", "sh010.blend"), "ab") as fh:
    fh.write(b" and some unsubmitted work")
check("змінений файл не збігається ні з чим", api.which_version(
    "Shots/sh010.blend") == {"rev": None})

print("--- Api: залежності й «хто використовує» ---")
fl = api.file_links("Shots/sh010.blend")
dp = fl.get("deps") or {}
check("зведення замість 34 посилань поіменно",
      dp.get("state") == "ok" and dp["counts"].get("packed") == 30
      and len(dp["problems"]) == 2, dp)
check("проблеми — лише missing/absolute; external — не проблема",
      sorted(p["state"] for p in dp["problems"]) == ["absolute", "missing"]
      and dp["counts"].get("external") == 1)
check("ціль проблеми — у шляхах копії",
      any(p["target"] == "tex/gone.png" for p in dp["problems"]), dp["problems"])
check("сцена тягне файл, що зараз їде з сервера",
      dp["uses"] == 2 and dp["newer"] == ["tex/wood.png"], dp)
fl = api.file_links("tex/wood.png")
check("текстура: хто використовує, у шляхах копії",
      fl.get("used_by", {}).get("users") == ["Shots/sh010.blend", "Shots/sh020.blend"],
      fl)
check("для текстури залежностей не питаємо", "deps" not in fl)
ub = api.used_by_many(["tex/wood.png", "Shots/sh020.blend", "notes.txt"])
check("перед видаленням: хто зламається, крім того, що теж видаляється",
      ub == {"tex/wood.png": ["Shots/sh010.blend"]}, ub)

print("--- Api: сторінки на сайті складаються тут ---")
opened = []
real_open = app.desktop.open_path
app.desktop.open_path = lambda u: opened.append(u) or True
api.open_web("file", "Shots/сцена 1.blend")
api.open_web("mine")
api.open_web("board")
app.desktop.open_path = real_open
check("сторінка файлу — з /trunk і закодованим іменем",
      opened[0] == HOST + "/browse/demo/tree/trunk/Shots/%D1%81%D1%86%D0%B5%D0%BD%D0%B0%201.blend",
      opened[0])
check("мої задачі й дошка", opened[1:] == [HOST + "/browse/mine",
                                          HOST + "/browse/demo/tasks/"], opened[1:])
try:
    api.open_web("https://evil.example/")
    check("будь-яка інша сторінка — відмова", False)
except sc.SvnError:
    check("будь-яка інша сторінка — відмова", True)

print("--- Api: без сервера все мовчки вимикається ---")
api2 = app.Api()
api2.conf = {"format": 2, "current": "p2", "projects": [
    {"id": "p2", "name": "x", "wc": wc, "url": "svn://host/x", "username": USER}]}
api2._last["p2"] = {"info": {"root": "svn://host/x", "url": "svn://host/x"}}
check("не svn-native: ok=False", api2.server_status().get("ok") is False)
check("задачі — порожньо, без винятку", api2.tasks_overview().get("tasks") == [])
check("прев'ю — порожньо", api2.previews([{"path": "a.blend", "rev": 1}]) == {})
check("перевірка видалення — порожньо", api2.used_by_many(["a.png"]) == {})
check("панель файлу — ok=False", api2.file_links("a.blend") == {"ok": False})

known_before = len(api._tasks["p1"]["out"]["tasks"])
server.shutdown()
check("сервер зник посеред роботи: задачі лишаються з помилкою",
      (lambda o: o.get("ok") is False and o.get("error") and
       len(o.get("tasks") or []) == known_before > 0)(api.tasks_overview(force=True)))


# ------------------------------------------------ 4. відмова хука: текст
print("--- відмова хука: що бачить людина ---")
RAW_COMMIT = (
    "Sending        Shots\\sh010.blend\n"
    "Transmitting file data .done\n"
    "Committing transaction...\n"
    "svn: E165001: Commit failed (details follow):\n"
    "svn: E165001: Commit blocked by pre-commit hook (exit code 1) with output:\n"
    "These files are assigned to someone else:\n"
    "  /trunk/Shots/sh010.blend ?\\226?\\128?\\148 olena (Animation, In progress)\n"
    "Only the assignee or a supervisor can commit them. Ask a supervisor to "
    "reassign the task.")
said = sc.hook_refusal(RAW_COMMIT)
check("коміт: текст хука дослівно", said ==
      "These files are assigned to someone else:\n"
      "  /trunk/Shots/sh010.blend — olena (Animation, In progress)\n"
      "Only the assignee or a supervisor can commit them. Ask a supervisor to "
      "reassign the task.", said)
RAW_LOCK = ("svn: warning: W165001: Lock blocked by pre-lock hook (exit code 1) "
            "with output:\nThese files are assigned to someone else:\n"
            "  /trunk/a.blend ?\\226?\\128?\\148 olena (task, To do)\n"
            "Only the assignee or a supervisor can lock them.\n"
            "svn: E200009: One or more locks could not be obtained")
said = sc.hook_refusal(RAW_LOCK)
check("лок: хвіст svn після виводу хука відрізано",
      said.endswith("can lock them.") and "E200009" not in said, said)
check("humanize віддає текст хука, а не «хтось тримає лок»",
      sc.humanize(RAW_LOCK) == said)
check("хук мовчки відмовив — усе одно пояснення",
      sc.hook_refusal("svn: E165001: Commit blocked by pre-commit hook "
                      "(exit code 1)") == sc.HOOK_SILENT)
check("не хук — None", sc.hook_refusal("svn: E170013: Unable to connect") is None)
check("зламана послідовність байтів лишається як була",
      sc._unfuzz("a ?\\255?\\128 b") == "a ?\\255?\\128 b")


# ------------------------------------ 5. справжній svn зі справжніми хуками
print("--- справжні хуки svn ---")
repo = os.path.join(BASE, "repo")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace(os.sep, "/").lstrip("/")
hwc = os.path.join(BASE, "hwc")
sc.checkout(url, hwc)
os.makedirs(os.path.join(hwc, "Shots"))
for rel, data in (("notes.txt", b"one"), ("Shots/a.blend", b"BLEND" * 10),
                  ("Shots/b.blend", b"BLEND" * 11)):
    with open(os.path.join(hwc, rel.replace("/", os.sep)), "wb") as fh:
        fh.write(data)
sc.add(hwc, ["notes.txt", "Shots"])
sc.commit(hwc, ["notes.txt", "Shots"], "seed")

LINES = ["These files are assigned to someone else:",
         "  /Shots/a.blend - olena (Animation, In progress)",
         "Only the assignee or a supervisor can commit them."]
hooks = os.path.join(repo, "hooks")
for name in ("pre-commit", "pre-lock"):
    if os.name == "nt":
        body = "@echo off\r\n" + "".join(">&2 echo %s\r\n" % l for l in LINES) + "exit 1\r\n"
        path = os.path.join(hooks, name + ".bat")
    else:
        body = "#!/bin/sh\n" + "".join("echo '%s' >&2\n" % l for l in LINES) + "exit 1\n"
        path = os.path.join(hooks, name)
    with open(path, "w", newline="") as fh:
        fh.write(body)
    if os.name != "nt":
        os.chmod(path, 0o755)

with open(os.path.join(hwc, "notes.txt"), "wb") as fh:
    fh.write(b"two")
try:
    sc.commit(hwc, ["notes.txt"], "should be refused")
    check("хук pre-commit відмовив", False)
except sc.RuleError as e:
    check("коміт: RuleError з текстом хука дослівно",
          str(e).splitlines() == LINES, str(e))
except sc.SvnError as e:
    check("коміт: RuleError з текстом хука дослівно", False, "SvnError: %s | %s" % (e, e.raw))
try:
    sc.lock(hwc, ["Shots/a.blend"])
    check("хук pre-lock відмовив", False)
except sc.RuleError as e:
    check("лок: RuleError з текстом хука, без хвоста svn",
          str(e).splitlines() == LINES, str(e))
except sc.SvnError as e:
    check("лок: RuleError з текстом хука, без хвоста svn", False,
          "SvnError: %s | %s" % (e, e.raw))
r = sc.lock_folder(hwc, "Shots", me="olena")
check("лок теки: відмову не проковтнуто", r.get("refused") and
      "assigned to someone else" in r["refused"] and r["mine"] == 0, r)


# ---------------------------------- 6. конфлікт: обидві сторони картинками
print("--- конфлікт: що в тебе і що в колеги ---")
crepo = os.path.join(BASE, "crepo")
subprocess.run([sc.SVNADMIN, "create", crepo], check=True, capture_output=True)
curl = "file:///" + crepo.replace(os.sep, "/").lstrip("/")
A, B = os.path.join(BASE, "A"), os.path.join(BASE, "B")
sc.checkout(curl, A)
MINE, THEIRS = png(200, 10, 10), png(10, 10, 200)


def put(wcdir, data):
    full = os.path.join(wcdir, "tex.png")
    if os.path.exists(full):
        os.chmod(full, 0o666)
    with open(full, "wb") as fh:
        fh.write(data)


put(A, png(1, 1, 1))
sc.add(A, ["tex.png"])
sc.commit(A, ["tex.png"], "base")
sc.checkout(curl, B)
put(A, THEIRS)
sc.commit(A, ["tex.png"], "colleague")
put(B, MINE)
sc.update(B)
row = [f for f in sc.status(B) if f["path"] == "tex.png"]
check("конфлікт справді є", row and row[0]["status"] == "conflicted", row)
api3 = app.Api()
api3.conf = {"format": 2, "current": "p3", "projects": [
    {"id": "p3", "name": "c", "wc": B, "url": curl, "username": "b"}]}
cp = api3.conflict_previews("tex.png")


def raw_of(uri):
    return base64.b64decode((uri or ",").split(",", 1)[1]) if uri else None


check("твоя сторона — твій файл", raw_of(cp.get("mine")) == MINE)
check("сторона колеги — копія, яку лишив svn", raw_of(cp.get("theirs")) == THEIRS,
      cp.get("theirs_rev"))
check("ревізія колеги відома", cp.get("theirs_rev") == 2, cp.get("theirs_rev"))

print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
shutil.rmtree(BASE, ignore_errors=True)
sys.exit(1 if FAIL else 0)
