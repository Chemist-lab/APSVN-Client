# -*- coding: utf-8 -*-
"""Мультипроєктність: міграція, паролі, перемикання, забування.

Сценарії взято з розбору відмов — саме ті, у яких стара реалізація мовчки
губила роботу або список проєктів.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import svn_client as sc
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_proj_")
app.CONF_DIR = os.path.join(base, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.LOG = os.path.join(app.CONF_DIR, "error.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")
os.makedirs(app.CONF_DIR, exist_ok=True)


class FakeKeyring:
    def __init__(self):
        self.d = {}
        self.fail = False

    def set_password(self, s, u, p):
        if self.fail:
            raise RuntimeError("сховище недоступне")
        self.d[(s, u)] = p

    def get_password(self, s, u):
        return self.d.get((s, u))


kr = FakeKeyring()
app.keyring = kr

svnadmin = sc.SVNADMIN


def make_repo(tag):
    r = os.path.join(base, "repo_" + tag)
    subprocess.run([svnadmin, "create", r], check=True, capture_output=True)
    return "file:///" + r.replace("\\", "/")


URL_A, URL_B = make_repo("a"), make_repo("b")
WC_A = os.path.join(base, "Мультик")            # кирилиця у шляхах
WC_B = os.path.join(base, "Реклама")

print("=" * 66)
print("1. Міграція старого плоского конфіга")
print("=" * 66)
old = {"wc": WC_A, "url": URL_A, "username": "anya", "name": "Мультик"}
with open(app.CONF, "w", encoding="utf-8") as fh:
    json.dump(old, fh, ensure_ascii=False)
os.makedirs(WC_A, exist_ok=True)
sc.checkout(URL_A, WC_A)

api = app.Api()
check("старий конфіг перетворився на один проєкт", len(api.projects) == 1,
      api.projects)
check("поточний проєкт обрано", api.c.get("url") == URL_A, api.c)
check("імʼя збережено", api.c.get("name") == "Мультик")

# старий пароль лежав під логіном — новий код мусить його ще бачити
kr.d[("APSVN", "anya")] = "старий-пароль"
check("пароль зі старого ключа підхоплюється",
      api._creds()[1] == "старий-пароль", api._creds()[0])

print()
print("=" * 66)
print("2. Другий проєкт: однаковий логін, ІНШИЙ пароль")
print("=" * 66)
api.add_project(URL_B, WC_B, "anya", "пароль-Б", name="Реклама")
check("проєктів стало два", len(api.projects) == 2, [p["name"] for p in api.projects])
check("активним став новий", api.c.get("name") == "Реклама")

pid_a = [p["id"] for p in api.projects if p["name"] == "Мультик"][0]
pid_b = [p["id"] for p in api.projects if p["name"] == "Реклама"][0]
check("id проєктів різні", pid_a != pid_b)

check("пароль Б віддається для Б", api._creds()[1] == "пароль-Б")
api.switch_project(pid_a)
check("пароль А НЕ затерто другим проєктом",
      api._creds()[1] == "старий-пароль", api._creds()[1])

# і навпаки: свій пароль у кожного
api.set_password("новий-А")
check("новий пароль ліг саме в проєкт А", api._creds()[1] == "новий-А")
api.switch_project(pid_b)
check("проєкт Б свого пароля не втратив", api._creds()[1] == "пароль-Б")
api.switch_project(pid_a)

print()
print("=" * 66)
print("3. Конфіг переживає стару збірку APSVN")
print("=" * 66)
doc = json.load(open(app.CONF, encoding="utf-8"))
check("у файлі є список проєктів", len(doc.get("projects", [])) == 2)
check("є дзеркало поточного у старих ключах",
      doc.get("wc") == WC_A and doc.get("url") == URL_A,
      {k: doc.get(k) for k in ("wc", "url", "name")})
check("формат помічено", doc.get("format") == app.FORMAT)
check("резервну копію зроблено", os.path.isfile(app.CONF + ".bak"))

# стара збірка перезаписала документ плоским записом
with open(app.CONF, "w", encoding="utf-8") as fh:
    json.dump({"wc": WC_B, "url": URL_B, "username": "anya",
               "name": "Реклама"}, fh, ensure_ascii=False)
c2 = app.load_conf()
check("плоский залишок читається як один проєкт", len(c2["projects"]) == 1, c2)
check("і це саме той проєкт, що був відкритий", c2["projects"][0]["url"] == URL_B)

print()
print("=" * 66)
print("4. Побитий конфіг не веде до втрати списку")
print("=" * 66)
with open(app.CONF, "w", encoding="utf-8") as fh:
    fh.write("{це не json")
c3 = app.load_conf()
check("побитий конфіг відкинуто, узято .bak", len(c3.get("projects", [])) == 2, c3)
check("побитий файл збережено для розбору",
      any(f.startswith("config.json.broken-") for f in os.listdir(app.CONF_DIR)),
      os.listdir(app.CONF_DIR))

# повертаємо робочий стан
api = app.Api()
api.switch_project(pid_a)

print()
print("=" * 66)
print("5. Зникла тека НЕ кидає в майстер підключення")
print("=" * 66)
saved_wc = api.c["wc"]
api.c["wc"] = os.path.join(base, "відпалий-диск")
s = api.state()
check("проєкт лишається налаштованим", s.get("configured") is True, s.get("configured"))
check("повідомлено, що тека недоступна", bool(s.get("broken")), s.get("broken"))
check("випадайка проєктів нікуди не зникла", len(s.get("projects", [])) == 2)
check("можна перемкнутися на робочий проєкт", api.switch_project(pid_b) is True)
api.switch_project(pid_a)
api.c["wc"] = saved_wc
check("після повернення теки стан здоровий",
      api.state().get("broken") is None, api.state().get("broken"))

print()
print("=" * 66)
print("6. Захист від підключення в чужу або вкладену теку")
print("=" * 66)
try:
    api.add_project(URL_B, WC_A, "anya", "x")     # у теці лежить проєкт А
    check("чужу теку відхилено", False, "пройшло, а не мало")
except sc.SvnError as e:
    check("чужу теку відхилено", "different project" in str(e), e)
check("список проєктів не зіпсовано невдалою спробою", len(api.projects) == 2)

nested = os.path.join(WC_A, "всередині")
os.makedirs(nested, exist_ok=True)
try:
    api.add_project(URL_B, nested, "anya", "x")
    check("вкладену теку відхилено", False, "пройшло, а не мало")
except sc.SvnError as e:
    check("вкладену теку відхилено", "inside another project" in str(e), e)

print()
print("=" * 66)
print("7. Стан не тече між проєктами")
print("=" * 66)
open(os.path.join(WC_A, "тільки-в-А.blend"), "wb").write(b"A" * 100)
sa = api.state()
check("файл проєкту А видно", any(f["path"] == "тільки-в-А.blend"
                                  for f in sa["files"]), sa["files"])
check("state() називає свій проєкт", sa["pid"] == pid_a)
api.switch_project(pid_b)
sb = api.state()
check("у проєкті Б файлів А немає",
      not any(f["path"] == "тільки-в-А.blend" for f in sb["files"]), sb["files"])
check("state() назвав уже інший проєкт", sb["pid"] == pid_b)
check("імʼя проєкту в стані правильне", sb["name"] == "Реклама")

print()
print("=" * 66)
print("8. Перемикання під довгою операцією заборонене")
print("=" * 66)
api.busy.set()
try:
    api.switch_project(pid_a)
    check("перемикання під час обміну заблоковано", False, "пройшло")
except sc.SvnError as e:
    check("перемикання під час обміну заблоковано", "Please wait" in str(e), e)
api.busy.clear()

print()
print("=" * 66)
print("9. «Прибрати зі списку» не чіпає файли й попереджає про локи")
print("=" * 66)
api.switch_project(pid_a)
open(os.path.join(WC_A, "робота.blend"), "wb").write(b"B" * 100)
api.do_commit(["робота.blend"], "щоб було що зайняти")
api.do_lock(["робота.blend"])
msg = api.forget_project(pid_a)
check("проєкт зник зі списку", len(api.projects) == 1, [p["name"] for p in api.projects])
check("попереджено про зайняті файли", "locked by you" in msg, msg)
check("файли на диску цілі", os.path.isfile(os.path.join(WC_A, "робота.blend")))
check("поточним став той, що лишився", api.c["id"] == pid_b)
check("поки лишається хоч один проєкт — майстра немає",
      api.state().get("configured") is True)
check("прибраний проєкт не воскресає з диска",
      len(app.load_conf()["projects"]) == 1, app.load_conf()["projects"])
api.forget_project(pid_b)
check("коли проєктів не лишилось — майстер",
      api.state().get("configured") is False, api.state())

print()
print("=" * 66)
print("9b. «Більше не питати» переживає перезапуск")
print("=" * 66)
# У вебвʼю localStorage не годиться: pywebview щоразу піднімає сервер на
# НОВОМУ порту, тож сховище браузера прив'язане до порту й помирає з ним.
api2 = app.Api()
api2.add_project(URL_A, WC_A, "anya", "x", name="Знову")
check("спочатку налаштувань немає", api2.prefs() == {}, api2.prefs())
check("стан віддає порожні налаштування",
      api2.state().get("prefs") == {}, api2.state().get("prefs"))
api2.set_pref("lock_open_silent", True)
check("налаштування збережено", api2.prefs().get("lock_open_silent") is True)
check("воно є у стані для інтерфейсу",
      api2.state()["prefs"].get("lock_open_silent") is True)
again = app.Api()
check("пережило перезапуск застосунку",
      again.prefs().get("lock_open_silent") is True, again.prefs())
doc = json.load(open(app.CONF, encoding="utf-8"))
check("лежить саме в config.json", doc.get("prefs", {}).get("lock_open_silent") is True,
      doc.get("prefs"))
again.set_pref("lock_open_silent", False)
check("вимикається так само", app.Api().prefs().get("lock_open_silent") is False)

print()
print("=" * 66)
print("10. Помилка сховища паролів не мовчить")
print("=" * 66)
kr.fail = True
try:
    api.add_project(URL_A, os.path.join(base, "ще-одна"), "anya", "x")
    check("провал збереження пароля повідомлено", False, "промовчало")
except sc.SvnError as e:
    check("провал збереження пароля повідомлено", "could not be saved" in str(e), e)
kr.fail = False

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 66)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 66)
sys.exit(1 if FAIL else 0)
