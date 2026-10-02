# -*- coding: utf-8 -*-
"""Лічильник байтів на «трубі» між svn і сервером — для чесного поступу здачі.

svn на фазі «Transmitting file data» мовчить: крапки в цьому рядку не
пропорційні обсягу (одна на 64 МБ), а лічильники вводу-виводу процесу
мережевого трафіку не бачать (дослід 2026-10-02: svn звантажив ~17 КБ, а
OtherTransferCount показав 7 КБ). Тому APSVN на час здачі ставить між svn і
сервером найпростіший проксі — CONNECT-тунель на 127.0.0.1 — і рахує байти,
що йдуть у бік сервера. svn вмикає його своїм же параметром лише для цієї
команди (servers:global:http-proxy-*), системних налаштувань ніхто не чіпає.

Чого він НЕ робить і не може:
  * не бачить вмісту — TLS лишається наскрізним між svn і сервером, через
    тунель їдуть уже зашифровані байти (файли, пароль — нічого не видно);
  * не пускає нікуди, крім сервера проєкту, і лише з цього ж комп'ютера;
  * не подвоює трафік: ділянка svn -> тунель іде всередині машини (loopback),
    назовні байти виходять один раз.
Коштує ~4% одного ядра на кожні 100 МБ/с (замір: 3 ГіБ за 1.4 с).
"""
import socket
import threading

BUF = 256 * 1024
HEAD_MAX = 16 * 1024


def _host_port(target):
    """«host:port» з рядка CONNECT -> (host у нижньому регістрі, port) або None."""
    host, sep, port = str(target or "").rpartition(":")
    if not sep or not port.isdigit():
        return None
    host = host.strip("[]").lower()          # IPv6 приходить у дужках
    return (host, int(port)) if host else None


class Meter:
    """CONNECT-тунель на 127.0.0.1, що рахує байти. Лише до host:port."""

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

    def svn_args(self):
        """Як сказати svn іти саме через цей тунель — лише для однієї команди."""
        return ["--config-option", "servers:global:http-proxy-host=127.0.0.1",
                "--config-option", "servers:global:http-proxy-port=%d" % self.port]

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

    # --- нутрощі ------------------------------------------------------------
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
                return                      # вхід закрито — лічильник зупинено
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
            c.settimeout(None)
            s.settimeout(None)
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
