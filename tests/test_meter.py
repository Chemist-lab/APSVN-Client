# -*- coding: utf-8 -*-
"""Лічильник байтів на трубі між svn і сервером (app/meter.py) і поступ здачі.

Без мережі: «сервер» тут — локальний сокет. Справжній svn через тунель до
живого сервера перевіряє test_live.py (лише читання).
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
        while True:
            k = c.recv_into(buf)
            if not k:
                break
            n += k
        self.got.append(n)
        c.sendall(b"OK %d" % n)
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


print("=" * 64)
print("1. Тунель: точний підрахунок, відповідь після кінця запису")
print("=" * 64)
sink = Sink()
g = meter.Meter("127.0.0.1", sink.port)
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
check("параметр для svn — лише на цю команду",
      g.svn_args() == ["--config-option", "servers:global:http-proxy-host=127.0.0.1",
                       "--config-option",
                       "servers:global:http-proxy-port=%d" % g.port])
for raw, want in (("svn.example.com:443", ("svn.example.com", 443)),
                  ("SVN.Example.com:443", ("svn.example.com", 443)),
                  ("[::1]:8443", ("::1", 8443)), ("host", None), (":443", None)):
    check("розбір «%s»" % raw, meter._host_port(raw) == want, meter._host_port(raw))

print()
print("=" * 64)
print("3. Кілька тунелів разом і зупинка")
print("=" * 64)
g2 = meter.Meter("127.0.0.1", sink.port)
res = []
ths = [threading.Thread(target=lambda: res.append(
    tunnel(g2, b"127.0.0.1:%d" % sink.port, os.urandom(8 * MB)))) for _ in range(3)]
[t.start() for t in ths]
[t.join() for t in ths]
check("три тунелі разом — лічильник складає", g2.up == 24 * MB and g2.conns == 3,
      (g2.up, g2.conns))
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
g.stop()

print()
print("=" * 64)
print("4. Поступ здачі з лічильника: відсотки, швидкість, залишок")
print("=" * 64)


class Fake:
    up = 0


fake = Fake()
seen = []
n = sc._notifier(seen.append, "upload", total=2, total_bytes=100 * MB, meter=fake)
n.line("Sending        a.blend")
n.line("Adding  (bin)  b.png")
check("перелік файлів — як і був (N з M)", seen[-1]["phase"] == "prepare" and
      seen[-1]["pct"] == 100, seen[-1])
n.line("Transmitting file data")
check("передача з лічильником — є відсоток", seen[-1]["phase"] == "send" and
      seen[-1]["pct"] == 0 and seen[-1]["measured"], seen[-1])
n.io(None)                                   # перша мітка
n._prev = (time.monotonic() - 1.0, 0)
fake.up = 10 * MB
n.io(None)
e = seen[-1]
check("10 МБ зі 100 — 10%", e["pct"] == 10 and e["bytes"] == 10 * MB, e)
check("швидкість — з байтів на трубі", e["rate"] and abs(e["rate"] - 10 * MB) < MB, e["rate"])
check("залишок — з цієї швидкості (~9 с)", e["eta"] in (8, 9, 10), e["eta"])
n._prev = (time.monotonic() - 1.0, fake.up)
fake.up = 150 * MB                           # TLS і заголовки зверху обсягу файлів
n.io(None)
check("більше за обсяг файлів — 99%, а не 150% (решта — на сервері)",
      seen[-1]["pct"] == 99 and seen[-1]["eta"] is None, seen[-1])
n.line("Committing transaction")
check("«Committing transaction» — уже без відсотків", seen[-1]["phase"] == "finalize"
      and seen[-1]["pct"] is None and seen[-1]["eta"] is None, seen[-1])
old = sc._notifier(seen.append, "upload", total=1, total_bytes=100 * MB, rate_hint=5 * MB)
old.line("Transmitting file data")
check("без лічильника — як раніше: без відсотків, оцінка за історією",
      seen[-1]["pct"] is None and seen[-1]["eta"] is not None and not seen[-1]["measured"],
      seen[-1])

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
real_commit, real_for = sc.commit, app.Api._meter_for


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
finally:
    sc.commit, app.Api._meter_for = real_commit, real_for

import shutil  # noqa: E402
shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
