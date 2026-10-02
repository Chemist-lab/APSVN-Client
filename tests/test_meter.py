# -*- coding: utf-8 -*-
"""Лічильник байтів на трубі між svn і сервером (app/meter.py) і поступ здачі.

Без мережі: «сервер» тут — локальний сокет. Справжній svn через тунель до
живого сервера перевіряє test_live.py (лише читання).

Смуга здачі стоїть на тому, скільки svn уже записав у .svn (sc._io_counts):
дослід 2026-10-02 на локальному svnserve дав рівно 1.00x розміру файлу для
нового, зміненого частково й зміненого цілком. svnserve у збірку не входить,
тож тут — розрахунки поступу й наскрізна перевірка на file://, де svn.exe пише
ще й у сховище (тому там «не менше», а не «рівно»).
"""
import getpass
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import meter
import svn_client as sc
import app

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


MB = 1024 * 1024


class Sink:
    """«Сервер»: читає все до кінця, потім відповідає скільки прийняв."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.got = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c):
        n = 0
        buf = bytearray(1 << 20)
        try:
            while True:
                k = c.recv_into(buf)
                if not k:
                    break
                n += k
            self.got.append(n)
            c.sendall(b"OK %d" % n)
        except OSError:
            pass            # тунель обірвали навмисно (перевірка зупинки) — кінець
        c.close()


def tunnel(g, target, payload=b"", chunk=1 << 20):
    """Клієнт, як svn: CONNECT, потім дані, кінець запису, читання відповіді."""
    s = socket.create_connection(("127.0.0.1", g.port))
    s.sendall(b"CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n" % (target, target))
    head = b""
    while b"\r\n\r\n" not in head:
        k = s.recv(4096)
        if not k:
            break
        head += k
    status = head.split(b"\r\n", 1)[0].decode()
    if " 200 " not in status + " ":
        s.close()
        return status, None
    sent = 0
    while sent < len(payload):
        s.sendall(payload[sent:sent + chunk])
        sent += len(payload[sent:sent + chunk])
    s.shutdown(socket.SHUT_WR)            # svn закінчив слати — відповідь ще йде
    back = b""
    while True:
        k = s.recv(65536)
        if not k:
            break
        back += k
    s.close()
    return status, back


def settle(g, timeout=3.0):
    """Окремий процес звітує раз на 0.2 с — дочекатись, поки цифри встоять."""
    end = time.time() + timeout
    last = None
    while time.time() < end:
        cur = (g.up, g.down, g.conns, g.refused)
        if cur == last:
            return cur
        last = cur
        time.sleep(0.45)
    return last


print("=" * 64)
print("1. Тунель: точний підрахунок, відповідь після кінця запису")
print("=" * 64)
sink = Sink()
g = meter.Relay("127.0.0.1", sink.port)
data = os.urandom(64 * MB)
t0 = time.perf_counter()
status, back = tunnel(g, b"127.0.0.1:%d" % sink.port, data)
took = time.perf_counter() - t0
check("CONNECT до дозволеного сервера — 200", "200" in status, status)
check("до «сервера» дійшли всі 64 МБ", sink.got[-1:] == [64 * MB], sink.got)
check("лічильник «до сервера» — рівно стільки ж", g.up == 64 * MB, g.up)
check("відповідь сервера після кінця запису дійшла цілою",
      back == b"OK %d" % (64 * MB), back)
check("і порахована в інший бік", g.down == len(back), g.down)
check("тунель один, і він дійшов до сервера", g.conns == 1, g.conns)
print("  (64 МБ крізь тунель за %.2f с)" % took)

print()
print("=" * 64)
print("2. Нікуди, крім сервера проєкту")
print("=" * 64)
st, _ = tunnel(g, b"127.0.0.1:%d" % (sink.port + 1))
check("інший порт — 403", st.startswith("HTTP/1.1 403"), st)
st, _ = tunnel(g, b"example.com:443")
check("інший сервер — 403", st.startswith("HTTP/1.1 403"), st)
s = socket.create_connection(("127.0.0.1", g.port))
s.sendall(b"GET http://127.0.0.1:%d/ HTTP/1.1\r\n\r\n" % sink.port)
check("звичайний запит (не CONNECT) — 405", s.recv(100).startswith(b"HTTP/1.1 405"))
s.close()
check("відмови пораховано, а до сервера ніхто зайвий не дійшов",
      g.refused == 3 and g.conns == 1, (g.refused, g.conns))
check("слухає лише 127.0.0.1", g._srv.getsockname()[0] == "127.0.0.1")
for raw, want in (("svn.example.com:443", ("svn.example.com", 443)),
                  ("SVN.Example.com:443", ("svn.example.com", 443)),
                  ("[::1]:8443", ("::1", 8443)), ("host", None), (":443", None)):
    check("розбір «%s»" % raw, meter._host_port(raw) == want, meter._host_port(raw))

print()
print("=" * 64)
print("3. Окремий процес: ті самі цифри, кілька тунелів, зупинка")
print("=" * 64)
g2 = meter.Meter("127.0.0.1", sink.port)
check("параметр для svn — лише на цю команду",
      g2.svn_args() == ["--config-option", "servers:global:http-proxy-host=127.0.0.1",
                        "--config-option",
                        "servers:global:http-proxy-port=%d" % g2.port])
res = []
ths = [threading.Thread(target=lambda: res.append(
    tunnel(g2, b"127.0.0.1:%d" % sink.port, os.urandom(8 * MB)))) for _ in range(3)]
[t.start() for t in ths]
[t.join() for t in ths]
settle(g2)
check("три тунелі разом — цифри з окремого процесу складаються",
      g2.up == 24 * MB and g2.conns == 3, (g2.up, g2.conns))
tunnel(g2, b"example.com:443")
settle(g2)
check("…і відмова звідти теж видна", g2.refused == 1, g2.refused)

# Головне, заради чого процес окремий: зайнятий Python-потік у програмі
# (вікно, міст до нього) тунелю не гальмує. У тому ж процесі він душив тунель
# до 6.7 МБ/с — так перша версія й дала художнику 1.7 МБ/с замість ~20.
SINK2 = r"""
import socket, sys
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
print(s.getsockname()[1], flush=True)
c, _ = s.accept()
buf = bytearray(1 << 20)
while c.recv_into(buf):
    pass
"""
SEND = r"""
import socket, sys, time
port, target = int(sys.argv[1]), sys.argv[2].encode()
s = socket.create_connection(("127.0.0.1", port))
s.sendall(b"CONNECT " + target + b" HTTP/1.1\r\n\r\n")
h = b""
while b"\r\n\r\n" not in h:
    h += s.recv(4096)
data = bytes(16 * 1024); total = 128 * 1024 * 1024; t0 = time.perf_counter(); sent = 0
while sent < total:
    s.sendall(data); sent += len(data)
s.close()
print("%.1f" % (total / (time.perf_counter() - t0) / 2**20))
"""
sp = subprocess.Popen([sys.executable, "-c", SINK2], stdout=subprocess.PIPE, text=True)
far = int(sp.stdout.readline())
g3 = meter.Meter("127.0.0.1", far)
spin_stop = threading.Event()


def spin():
    x = 0
    while not spin_stop.is_set():
        x += 1


threading.Thread(target=spin, daemon=True).start()
r = subprocess.run([sys.executable, "-c", SEND, str(g3.port), "127.0.0.1:%d" % far],
                   capture_output=True, text=True)
spin_stop.set()
g3.stop()
sp.wait(timeout=10)
speed = float(r.stdout.strip() or 0)
check("зайнятий потік у програмі тунель не гальмує (було 6.7 МБ/с)", speed > 100,
      "%.0f МБ/с" % speed)
hold = socket.create_connection(("127.0.0.1", g2.port))
hold.sendall(b"CONNECT 127.0.0.1:%d HTTP/1.1\r\n\r\n" % sink.port)
hold.recv(100)
g2.stop()
g2.stop()                                    # двічі — не страшно
hold.settimeout(5)
try:
    gone = hold.recv(10) == b""
except OSError:
    gone = True
check("зупинка закриває й живі тунелі", gone)
try:
    socket.create_connection(("127.0.0.1", g2.port), timeout=2).close()
    check("після зупинки вхід закрито", False)
except OSError:
    check("після зупинки вхід закрито", True)
check("…і процес тунелю завершився", g2._p.poll() is not None, g2._p.poll())
g.stop()

print()
print("=" * 64)
print("4. Поступ здачі: смуга — за файлами, мережа — окремо")
print("=" * 64)


class Fake:
    up = 0


def age(n, secs):
    """Зсунути «останній замір» швидкостей на secs у минуле."""
    for sp in (n._quick, n._steady, n._net):
        if sp.at is not None:
            sp.at -= secs


fake = Fake()
seen = []
n = sc._notifier(seen.append, "upload", total=2, total_bytes=100 * MB, meter=fake,
                 track_writes=True)
check("смуга за файлами (лічильники ОС є)", seen == [] and n.st["basis"] == "files"
      and n.st["measured"], n.st)
n.io((0, 40000))                             # wc.db, локи — ще не передача
n.line("Sending        a.blend")
n.line("Adding  (bin)  b.png")
check("перелік файлів — як і був (N з M)", seen[-1]["phase"] == "prepare" and
      seen[-1]["pct"] == 100, seen[-1])
n.line("Transmitting file data")
check("початок передачі — 0%, а записане досі не рахується",
      seen[-1]["phase"] == "send" and seen[-1]["pct"] == 0 and seen[-1]["bytes"] == 0,
      seen[-1])
n.io((0, 40000))                             # перша мітка швидкостей
n._send_at -= 1.0
age(n, 1.0)
fake.up = 1 * MB                             # мережею — лише різниця
n.io((0, 40000 + 10 * MB))
e = seen[-1]
check("10 МБ файлу зі 100 — 10%, хоч мережею пішов 1 МБ",
      e["pct"] == 10 and e["bytes"] == 10 * MB and e["sent"] == 1 * MB, e)
check("перші секунди — без залишку часу (перша оцінка лякає найбільше)",
      e["eta"] is None, e["eta"])
n._send_at -= 5.0
age(n, 1.0)
n.io((0, 40000 + 20 * MB))
e = seen[-1]
check("далі залишок — з того, як svn іде по файлах (80 МБ / 10 МБ/с ≈ 8 с)",
      e["eta"] in (7, 8, 9), e["eta"])
check("швидкість мережі — окремо, з байтів на трубі",
      e["sent_rate"] is not None and e["sent_rate"] < 2 * MB, e["sent_rate"])
eta_fast = e["eta"]
age(n, 1.0)
n.io((0, 40000 + 21 * MB))                  # почались змінені шматки: 1 МБ/с
e = seen[-1]
check("svn сповільнився — залишок одразу росте, а не обіцяє старе",
      e["eta"] is not None and e["eta"] > 2 * eta_fast, (eta_fast, e["eta"]))
age(n, 1.0)
n.io((0, 40000 + 130 * MB))                 # файл перезберегли більшим
e = seen[-1]
check("більше за обсяг — 99%, без залишку, а не 130%",
      e["pct"] == 99 and e["eta"] is None and e["bytes"] == 130 * MB, e)
n.line("Committing transaction")
check("«Committing transaction» — уже без відсотків", seen[-1]["phase"] == "finalize"
      and seen[-1]["pct"] is None and seen[-1]["eta"] is None, seen[-1])
n.line("Transmitting file data ....done")    # хвіст рядка приходить пізніше
check("дописаний рядок передачі не повертає з фінішу назад",
      seen[-1]["phase"] == "finalize", seen[-1]["phase"])
n.io((0, 40000 + 131 * MB))
check("останній замір після передачі теж доходить (для журналу)",
      seen[-1]["bytes"] == 131 * MB, seen[-1]["bytes"])
n.io(None)
check("лічильників раптом нема — поступ не падає", seen[-1]["bytes"] == 131 * MB)

seen.clear()
fake.up = 0
net = sc._notifier(seen.append, "upload", total=1, total_bytes=100 * MB, meter=fake)
net.line("Transmitting file data")
net.io(None)
net._send_at -= 5.0
age(net, 1.0)
fake.up = 30 * MB
net.io(None)
e = seen[-1]
check("без лічильників ОС — смуга за байтами на трубі, як раніше",
      e["basis"] == "network" and e["pct"] == 30 and e["bytes"] == 30 * MB and
      e["eta"] in (2, 3), e)

seen.clear()
old = sc._notifier(seen.append, "upload", total=1, total_bytes=100 * MB, rate_hint=5 * MB)
old.line("Transmitting file data")
check("без лічильника й без записаного — як раніше: без відсотків, оцінка за історією",
      seen[-1]["pct"] is None and seen[-1]["eta"] is not None and not seen[-1]["measured"],
      seen[-1])
dl = sc._notifier(seen.append, "download", total=3, track_writes=True)
check("записане — лише для здачі (на качанні svn пише сам файл)",
      dl.st["basis"] is None and not dl.st["measured"], dl.st)

print()
print("=" * 64)
print("5. Здача: лічильник лише для https; не дійшов до сервера — напряму")
print("=" * 64)
for url, want in (("https://svn.studio.test/svn/demo", ("svn.studio.test", 443)),
                  ("https://svn.studio.test:8443/svn/demo", ("svn.studio.test", 8443)),
                  ("http://svn.studio.test/svn/demo", None),
                  ("svn://svn.studio.test/demo", None), ("file:///C:/repo", None)):
    m = app.Api._meter_for(url)
    check("лічильник для %s" % url.split(":")[0],
          (m.allow if m else None) == want, m and m.allow)
    if m:
        m.stop()

base = tempfile.mkdtemp(prefix="apsvn_meter_")
app.CONF_DIR = os.path.join(base, "appdata")
app.CONF = os.path.join(app.CONF_DIR, "config.json")
app.ACTIVITY = os.path.join(app.CONF_DIR, "apsvn.log")
app.RESCUE = os.path.join(app.CONF_DIR, "rescue")
os.makedirs(app.CONF_DIR, exist_ok=True)


class FakeKeyring:
    def __init__(self): self.d = {}
    def set_password(self, s, u, p): self.d[(s, u)] = p
    def get_password(self, s, u): return self.d.get((s, u))


app.keyring = FakeKeyring()
app.Api.TIDY_DELAY = 0
app.Api.TIDY_EVERY = float("inf")
repo = os.path.join(base, "repo")
wc = os.path.join(base, "wc")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace("\\", "/").lstrip("/")
api = app.Api()
api.add_project(url, wc, getpass.getuser(), "pw", name="Лічильник")
with open(os.path.join(wc, "a.txt"), "w", encoding="utf-8") as fh:
    fh.write("перша")
sc.add(wc, ["a.txt"])
api.do_commit(["a.txt"], "перша здача")

calls = []
# сам staticmethod, а не функцію з нього: інакше, повернута в клас, вона
# стане звичайним методом і наступна здача впаде на зайвому self
real_commit, real_for = sc.commit, app.Api.__dict__["_meter_for"]


def fake_commit(*a, **kw):
    calls.append(kw.get("meter"))
    if kw.get("meter") is not None:
        raise sc.SvnError("Unable to connect to a repository at URL (via proxy)")
    return real_commit(*a, **kw)


sc.commit = fake_commit
app.Api._meter_for = staticmethod(lambda u: meter.Meter("127.0.0.1", 9))
try:
    with open(os.path.join(wc, "a.txt"), "w", encoding="utf-8") as fh:
        fh.write("друга")
    out = api.do_commit(["a.txt"], "друга здача")
    check("svn через лічильник до сервера не дійшов — здано напряму",
          sc.COMMIT_RE.search(out) and len(calls) == 2 and calls[0] is not None
          and calls[1] is None, (out, calls))
    with open(app.ACTIVITY, encoding="utf-8") as fh:
        check("…і це записано в журнал", "upload meter" in fh.read())

    class Reached(meter.Meter):
        def __init__(self, *a):
            super().__init__(*a)
            self.conns = 1                 # тунель до сервера був

    calls.clear()
    app.Api._meter_for = staticmethod(lambda u: Reached("127.0.0.1", 9))
    with open(os.path.join(wc, "a.txt"), "w", encoding="utf-8") as fh:
        fh.write("третя")
    try:
        api.do_commit(["a.txt"], "третя здача")
        check("дійшов до сервера й упав — помилка справжня, другої спроби немає", False)
    except sc.SvnError:
        check("дійшов до сервера й упав — помилка справжня, другої спроби немає",
              len(calls) == 1, calls)

    # Дійшов і впав ШВИДШЕ, ніж тунель устиг звітувати (звіт — раз на 0.2 с):
    # рішення «не дійшов» мусить ухвалюватись після зупинки тунелю, з його
    # останніми цифрами, а не з нулями, що ще не оновились.
    calls.clear()
    app.Api._meter_for = staticmethod(lambda u: meter.Meter("127.0.0.1", sink.port))

    def quick_fail(*a, **kw):
        calls.append(kw.get("meter"))
        g = kw.get("meter")
        if g is not None:
            tunnel(g, b"127.0.0.1:%d" % sink.port, b"x" * 10)
            raise sc.SvnError("svn: E160028: File is out of date")
        return real_commit(*a, **kw)

    sc.commit = quick_fail
    with open(os.path.join(wc, "a.txt"), "w", encoding="utf-8") as fh:
        fh.write("четверта")
    try:
        api.do_commit(["a.txt"], "четверта здача")
        check("дійшов і впав миттєво — теж без другої спроби", False)
    except sc.SvnError:
        check("дійшов і впав миттєво — теж без другої спроби", len(calls) == 1, calls)
finally:
    sc.commit, app.Api._meter_for = real_commit, real_for

print()
print("=" * 64)
print("6. Здача: обсяг передачі, підсумок, журнал")
print("=" * 64)
with open(os.path.join(wc, "old.bin"), "wb") as fh:
    fh.write(os.urandom(3 * MB))
sc.add(wc, ["old.bin"])
api.do_commit(["old.bin"], "старий файл")
sc.remove(wc, ["old.bin"])                    # видалено, але лежить на диску
check("видалений лежить на диску до кінця здачі",
      os.path.isfile(os.path.join(wc, "old.bin")))
with open(os.path.join(wc, "new.bin"), "wb") as fh:
    fh.write(os.urandom(1 * MB))
kws = []


def spy(*a, **kw):
    kws.append(kw)
    return real_commit(*a, **kw)


sc.commit = spy
try:
    out = api.do_commit(["old.bin", "new.bin"], "заміна")
finally:
    sc.commit = real_commit
check("здано", sc.COMMIT_RE.search(out), out)
check("обсяг передачі — лише новий файл (видалений не їде)",
      kws and kws[0]["total_bytes"] == 1 * MB, kws and kws[0]["total_bytes"])
check("на file:// записане не рахуємо (svn.exe пише ще й у сховище)",
      kws and kws[0]["track_writes"] is False, kws and kws[0]["track_writes"])


class Gauge:
    up, conns = 20 * MB, 1

    def stop(self):
        pass


def done_fake(*a, **kw):
    kws.append(kw)
    kw["progress"]({"kind": "upload", "phase": "finalize", "basis": "files",
                    "bytes": kw["total_bytes"], "total_bytes": kw["total_bytes"]})
    return "Sent. This is commit 99 — your team can see your work now."


ticks = []


def fake_submit(paths, note):
    """Здача з підробленим svn і лічильником; події поступу — у ticks (після
    здачі програма поступ скидає, тож дивитись треба під час неї)."""
    ticks.clear()
    sc.commit = done_fake
    app.Api._meter_for = staticmethod(lambda u: Gauge())
    api.c["url"] = "https://svn.studio.test/svn/demo"
    api._tick = ticks.append
    try:
        return api.do_commit(paths, note)
    finally:
        sc.commit, app.Api._meter_for = real_commit, real_for
        api.c["url"] = url
        del api._tick


with open(os.path.join(wc, "scene.blend"), "wb") as fh:
    fh.write(bytes(70 * MB))
kws.clear()
out = fake_submit(["scene.blend"], "велика сцена")
check("на https смуга — за записаним", kws and kws[0]["track_writes"] is True,
      kws and kws[0]["track_writes"])
check("новий файл — без «лише зміни» (вікну нема чого пояснювати)",
      ticks and ticks[-1].get("edited") is False, ticks[-1:])
check("підсумок окремим рядком: обсяг, час і що пішло мережею стиснутим",
      out.endswith("\n70.0 MB in 0s; 20.0 MB sent, compressed."), repr(out))
with open(app.ACTIVITY, encoding="utf-8") as fh:
    log = fh.read()
check("у журналі — скільки svn пройшов по файлах і скільки пішло мережею",
      "submit r99: 70.0 MB" in log and "(1.00x)" in log and "uploaded 20.0 MB" in log,
      log.strip().splitlines()[-1:])

# змінений файл (текстовий — бінарник без лока здачу не пройде)
with open(os.path.join(wc, "notes.txt"), "wb") as fh:
    fh.write(b"a" * (40 * MB))
sc.add(wc, ["notes.txt"])
api.do_commit(["notes.txt"], "нотатки")
with open(os.path.join(wc, "notes.txt"), "r+b") as fh:
    fh.write(b"b" * MB)
out = fake_submit(["notes.txt"], "правка нотаток")
check("змінений файл — вікно знає, що їде лише різниця",
      ticks and ticks[-1].get("edited") is True, ticks[-1:])
check("підсумок: «only the changes were sent»",
      out.endswith("\n40.0 MB in 0s; only the changes were sent (20.0 MB)."), repr(out))

print()
print("=" * 64)
print("7. Наскрізно: справжній svn, записане доходить до смуги")
print("=" * 64)
if not sc.desktop.WINDOWS:
    print("  (лічильники процесу є лише у Windows — пропущено)")
else:
    # такий, щоб здача тривала кілька замірів (вони — раз на 0.5 с)
    BIG = 192 * MB
    chunk = os.urandom(MB)
    with open(os.path.join(wc, "big.bin"), "wb") as fh:
        for i in range(BIG // MB):
            fh.write(chunk[i:] + chunk[:i])
    sc.add(wc, ["big.bin"])
    ev = []
    out = sc.commit(wc, ["big.bin"], "великий", progress=lambda e: ev.append(dict(e)),
                    total=1, total_bytes=BIG, track_writes=True)
    check("здано", sc.COMMIT_RE.search(out), out)
    send = [e for e in ev if e["phase"] == "send"]
    pcts = [e["pct"] for e in send]
    check("передача видна відсотками за файлами", send and all(
        e["basis"] == "files" and e["pct"] is not None for e in send), pcts)
    check("смуга рухається по ходу, а не стрибає з 0 у кінець",
          any(0 < x < 99 for x in pcts), pcts)
    check("смуга лише росте й не перескакує 99%",
          pcts == sorted(pcts) and max(pcts or [0]) <= 99, pcts)
    check("наприкінці svn пройшов увесь файл (на file:// — і більше: ще й сховище)",
          ev and ev[-1]["bytes"] >= BIG, ev and ev[-1]["bytes"])

import shutil  # noqa: E402
shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
