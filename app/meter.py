# -*- coding: utf-8 -*-
"""Лічильник байтів на «трубі» між svn і сервером — для чесного поступу здачі.

svn на фазі «Transmitting file data» мовчить: крапки в цьому рядку не
пропорційні обсягу (одна на 64 МБ), а лічильники вводу-виводу процесу
мережевого трафіку не бачать (дослід 2026-10-02: svn звантажив ~17 КБ, а
OtherTransferCount показав 7 КБ). Тому APSVN на час здачі ставить між svn і
сервером найпростіший проксі — CONNECT-тунель на 127.0.0.1 — і рахує байти,
що йдуть у бік сервера. svn вмикає його своїм же параметром лише для цієї
команди (servers:global:http-proxy-*), системних налаштувань ніхто не чіпає.

ТУНЕЛЬ — ОКРЕМИЙ ПРОЦЕС, і це не прикраса. Перша версія жила в процесі
програми й на справжній здачі дала 1.7 МБ/с замість звичних ~20: потоки Python
в одному процесі ділять GIL, і тунель після кожного шматка (запис TLS — до
16 КБ) чекав своєї черги за вікном і мостом до нього. Дослід: той самий тунель
у процесі з одним зайнятим Python-потоком — 6.7 МБ/с замість 2 ГБ/с. В окремому
процесі ділити нічого, і він дає те, що вміє мережа (живий тест: 37-44 МБ/с).
Програма лише читає від нього рядки «скільки пройшло» кілька разів на секунду.

Чого тунель НЕ робить і не може:
  * не бачить вмісту — TLS лишається наскрізним між svn і сервером, через
    тунель їдуть уже зашифровані байти (файли, пароль — нічого не видно);
  * не пускає нікуди, крім сервера проєкту, і лише з цього ж комп'ютера;
  * не подвоює трафік: ділянка svn -> тунель іде всередині машини (loopback),
    назовні байти виходять один раз.
"""
import os
import socket
import subprocess
import sys
import threading

BUF = 1024 * 1024
HEAD_MAX = 16 * 1024
SOCK_BUF = 4 * 1024 * 1024
STAT_EVERY = 0.2          # с: як часто тунель каже, скільки пройшло


def _host_port(target):
    """«host:port» з рядка CONNECT -> (host у нижньому регістрі, port) або None."""
    host, sep, port = str(target or "").rpartition(":")
    if not sep or not port.isdigit():
        return None
    host = host.strip("[]").lower()          # IPv6 приходить у дужках
    return (host, int(port)) if host else None


def _setopts(s):
    """Без затримки Nagle й із великими буферами: тунель лише перекладає
    байти, тож чекати, «поки назбирається», йому ні до чого."""
    for level, opt, val in ((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
                            (socket.SOL_SOCKET, socket.SO_SNDBUF, SOCK_BUF),
                            (socket.SOL_SOCKET, socket.SO_RCVBUF, SOCK_BUF)):
        try:
            s.setsockopt(level, opt, val)
        except OSError:
            pass


class Relay:
    """Сам тунель: CONNECT на 127.0.0.1, що рахує байти. Лише до host:port.

    Живе в ОКРЕМОМУ процесі (див. шапку); тут, у класі, — уся робота, щоб її
    можна було перевірити й напряму, без процесу.
    """

    def __init__(self, host, port):
        self.allow = (str(host).strip("[]").lower(), int(port))
        self.up = 0              # байти до сервера — це і є поступ здачі
        self.down = 0
        self.conns = 0           # тунелів, які справді дійшли до сервера
        self.refused = 0
        self._lock = threading.Lock()
        self._socks = set()
        self._stopped = False
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(16)
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True,
                         name="apsvn-meter").start()

    def stop(self):
        """Закрити вхід і всі тунелі. Безпечно кликати кілька разів."""
        with self._lock:
            self._stopped = True
            socks = list(self._socks)
            self._socks.clear()
        for s in [self._srv] + socks:
            try:
                s.close()
            except OSError:
                pass

    def _keep(self, s):
        with self._lock:
            if self._stopped:
                return False
            self._socks.add(s)
            return True

    def _drop(self, *socks):
        with self._lock:
            for s in socks:
                self._socks.discard(s)
        for s in socks:
            try:
                s.close()
            except OSError:
                pass

    def _count(self, way, n):
        with self._lock:
            if way == "up":
                self.up += n
            else:
                self.down += n

    def _accept(self):
        while True:
            try:
                c, _ = self._srv.accept()
            except OSError:
                return                      # вхід закрито — тунель зупинено
            if not self._keep(c):
                self._drop(c)
                return
            threading.Thread(target=self._tunnel, args=(c,), daemon=True,
                             name="apsvn-meter-conn").start()

    def _refuse(self, c, status):
        with self._lock:
            self.refused += 1
        try:
            c.sendall(("HTTP/1.1 %s\r\nContent-Length: 0\r\n\r\n" % status)
                      .encode("ascii"))
        except OSError:
            pass
        self._drop(c)

    def _tunnel(self, c):
        s = None
        try:
            c.settimeout(30)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = c.recv(4096)
                if not chunk or len(head) > HEAD_MAX:
                    self._drop(c)
                    return
                head += chunk
            first = head.split(b"\r\n", 1)[0].decode("latin-1").split()
            if len(first) < 2 or first[0].upper() != "CONNECT":
                return self._refuse(c, "405 Only CONNECT")
            if _host_port(first[1]) != self.allow:
                return self._refuse(c, "403 Only the project's server")
            try:
                s = socket.create_connection(self.allow, timeout=30)
            except OSError:
                return self._refuse(c, "502 Cannot reach the server")
            if not self._keep(s):
                self._drop(c, s)
                return
            for x in (c, s):
                x.settimeout(None)
                _setopts(x)
            with self._lock:
                self.conns += 1
            c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            rest = head.split(b"\r\n\r\n", 1)[1]
            if rest:
                s.sendall(rest)
                self._count("up", len(rest))
            back = threading.Thread(target=self._pipe, args=(s, c, "down"),
                                    daemon=True, name="apsvn-meter-down")
            back.start()
            self._pipe(c, s, "up")
            back.join()
            self._drop(c, s)
        except OSError:
            self._drop(*[x for x in (c, s) if x is not None])

    def _pipe(self, a, b, way):
        """Перекладати байти a -> b, рахуючи. Кінець a — це «a більше не
        шле», а не «розірвати все»: відповідь сервера ще може йти, тож далі
        передаємо лише кінець запису (shutdown SHUT_WR)."""
        buf = bytearray(BUF)
        mv = memoryview(buf)
        try:
            while True:
                n = a.recv_into(buf)
                if not n:
                    break
                b.sendall(mv[:n])
                self._count(way, n)
        except OSError:
            pass
        try:
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass


# --- окремий процес -----------------------------------------------------------
def _serve(host, port):
    """Тіло дочірнього процесу: тунель + рядки «скільки пройшло» в stdout.

    Кінець stdin — сигнал зупинитись: батько закрив трубу або сам упав, і тоді
    тунель не лишиться висіти сиротою.
    """
    relay = Relay(host, port)
    out = sys.stdout
    out.write("PORT %d\n" % relay.port)
    out.flush()
    done = threading.Event()

    def watch():
        try:
            sys.stdin.buffer.read()
        except Exception:
            pass
        done.set()

    threading.Thread(target=watch, daemon=True).start()
    last = (0, 0, 0, 0)

    def say():
        cur = (relay.up, relay.down, relay.conns, relay.refused)
        nonlocal last
        if cur != last:
            out.write("STAT %d %d %d %d\n" % cur)
            out.flush()
            last = cur

    try:
        while not done.wait(STAT_EVERY):
            say()
    finally:
        relay.stop()
        try:
            say()
        except Exception:
            pass


def _python():
    """Чим запустити тунель: python.exe поруч із pythonw.exe програми (з ним
    рядки в stdout надійні), без вікна консолі — прапорцем при запуску."""
    exe = sys.executable or "python"
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(alt):
            return alt
    return exe


class Meter:
    """Тунель в окремому процесі. Для решти програми — ті самі поля й методи:
    up, down, conns, refused, port, svn_args(), stop()."""

    START_TIMEOUT = 10

    def __init__(self, host, port):
        self.allow = (str(host).strip("[]").lower(), int(port))
        self.up = self.down = self.conns = self.refused = 0
        self.port = None
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        self._p = subprocess.Popen(
            [_python(), "-u", os.path.abspath(__file__), "--serve",
             self.allow[0], str(self.allow[1])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, **kw)
        killer = threading.Timer(self.START_TIMEOUT, self._kill)
        killer.start()
        try:
            first = self._p.stdout.readline().decode("ascii", "replace").split()
        finally:
            killer.cancel()
        if len(first) != 2 or first[0] != "PORT" or not first[1].isdigit():
            self._kill()
            raise OSError("the upload meter did not start")
        self.port = int(first[1])
        self._reader = threading.Thread(target=self._read, daemon=True,
                                        name="apsvn-meter-read")
        self._reader.start()

    def _read(self):
        for raw in self._p.stdout:
            parts = raw.decode("ascii", "replace").split()
            if len(parts) == 5 and parts[0] == "STAT" and all(x.isdigit() for x in parts[1:]):
                self.up, self.down, self.conns, self.refused = map(int, parts[1:])

    def _kill(self):
        try:
            self._p.kill()
        except OSError:
            pass

    def svn_args(self):
        """Як сказати svn іти саме через цей тунель — лише для однієї команди."""
        return ["--config-option", "servers:global:http-proxy-host=127.0.0.1",
                "--config-option", "servers:global:http-proxy-port=%d" % self.port]

    def stop(self):
        """Зупинити тунель і дочитати останні цифри. Безпечно кликати двічі."""
        try:
            self._p.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self._p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill()
        self._reader.join(timeout=2)


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--serve":
    _serve(sys.argv[2], int(sys.argv[3]))
