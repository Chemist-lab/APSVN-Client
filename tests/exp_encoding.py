# -*- coding: utf-8 -*-
"""Дослід: що саме svn.exe приймає на машині з ACP=cp1252.

Перевіряємо окремо дві осі:
  A) чи працює робоча копія, розташована за кириличним шляхом;
  B) як передати кириличне ІМʼЯ ФАЙЛУ всередині ASCII-копії.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

BIN = os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "svn")
SVN = os.path.join(BIN, "svn.exe")
SVNADMIN = os.path.join(BIN, "svnadmin.exe")
NW = 0x08000000
ACP = "cp%d" % ctypes.windll.kernel32.GetACP()
print("ACP =", ACP, "| OEMCP =", ctypes.windll.kernel32.GetOEMCP())
print()


def run(args, cwd=None, label=""):
    r = subprocess.run([SVN] + args, cwd=cwd, capture_output=True,
                       creationflags=NW, stdin=subprocess.DEVNULL)
    out = (r.stdout + r.stderr)
    txt = None
    for enc in ("utf-8", ACP, "cp1251"):
        try:
            txt = out.decode(enc); break
        except UnicodeDecodeError:
            pass
    txt = (txt or out.decode("mbcs", "replace")).strip()
    return r.returncode, txt


def short(p):
    buf = ctypes.create_unicode_buffer(2048)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 2048)
    return buf.value if n else None


base = tempfile.mkdtemp(prefix="apsvn_exp_")
repo = os.path.join(base, "repo")
subprocess.run([SVNADMIN, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace("\\", "/")

# ---------------------------------------------------------------- A: шлях WC
print("=" * 66)
print("A. Робоча копія за КИРИЛИЧНИМ шляхом")
print("=" * 66)
cyr_wc = os.path.join(base, "Робота")
os.makedirs(cyr_wc, exist_ok=True)
rc, txt = run(["checkout", url, "."], cwd=cyr_wc)
print("  checkout(cwd=кирилиця, ціль='.'):", "OK" if rc == 0 else "FAIL", "|", txt[:90])
if rc == 0:
    open(os.path.join(cyr_wc, "a.blend"), "wb").write(b"x" * 50)
    rc2, t2 = run(["add", "a.blend"], cwd=cyr_wc)
    print("  add ASCII-файла всередині:", "OK" if rc2 == 0 else "FAIL", "|", t2[:90])
    rc3, t3 = run(["commit", "-m", "test"], cwd=cyr_wc)
    print("  commit:", "OK" if rc3 == 0 else "FAIL", "|", t3[:90])

sp = short(cyr_wc)
print("  8.3 для кириличної теки:", repr(sp))
if sp:
    try:
        sp.encode(ACP); print("  -> 8.3 представний в ACP: ТАК")
    except UnicodeEncodeError:
        print("  -> 8.3 представний в ACP: НІ")

# ------------------------------------------------------- B: кириличне імʼя
print()
print("=" * 66)
print("B. Кириличне ІМʼЯ ФАЙЛУ в ASCII-копії")
print("=" * 66)
wc = os.path.join(base, "wc_ascii")
os.makedirs(wc, exist_ok=True)
rc, txt = run(["checkout", url, "."], cwd=wc)
print("  checkout ASCII:", "OK" if rc == 0 else "FAIL", "|", txt[:70])

NAME = "Сцена міста.blend"
open(os.path.join(wc, NAME), "wb").write(b"B" * 50)

variants = []
# 1) прямо в argv
variants.append(("argv напряму", lambda: run(["add", NAME], cwd=wc)))
# 2) targets-файл у різних кодуваннях
for enc in ("utf-8", "utf-8-sig", "cp1251", "utf-16-le"):
    def mk(enc=enc):
        fd, tf = tempfile.mkstemp(suffix=".txt"); os.close(fd)
        try:
            with open(tf, "w", encoding=enc, newline="\n") as fh:
                fh.write(NAME + "\n")
        except UnicodeEncodeError:
            return (99, "не кодується в " + enc)
        try:
            return run(["add", "--targets", tf], cwd=wc)
        finally:
            os.unlink(tf)
    variants.append(("targets (%s)" % enc, mk))
# 3) короткий шлях
sp_file = short(os.path.join(wc, NAME))
variants.append(("8.3 argv (%s)" % (os.path.basename(sp_file) if sp_file else "-"),
                 (lambda: run(["add", sp_file], cwd=wc)) if sp_file else (lambda: (99, "8.3 недоступний"))))

for label, fn in variants:
    rc, txt = fn()
    ok = rc == 0
    print("  %-22s %s | %s" % (label, "OK  " if ok else "FAIL", txt[:75]))
    if ok:
        # чи бачить svn його правильно після додавання
        rc2, t2 = run(["status", "--xml", "."], cwd=wc)
        good = NAME in t2
        print("       -> у status імʼя коректне:", "ТАК" if good else "НІ")
        run(["revert", "--depth", "infinity", "."], cwd=wc)

shutil.rmtree(base, ignore_errors=True)
