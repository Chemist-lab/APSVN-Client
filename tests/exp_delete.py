# -*- coding: utf-8 -*-
"""Як видалити файл, чиє імʼя не кодується в ANSI, якщо його вже нема на диску."""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import svn_client as sc

NAME = "звʼязок міста.txt"          # U+02BC — немає в cp1251/1252/жодній ANSI
ACP = sc._acp()
print("ACP:", ACP)
for enc in ("cp1252", "cp1251", "cp1250", "cp65001"):
    try:
        NAME.encode(enc); print("  %s: кодується" % enc)
    except (UnicodeEncodeError, LookupError) as e:
        print("  %s: НІ" % enc)
print()

base = tempfile.mkdtemp(prefix="exp_del_")
repo = os.path.join(base, "repo")
subprocess.run([sc.SVNADMIN, "create", repo],
               check=True, capture_output=True)
# .lstrip: на POSIX шлях уже починається з "/", і без цього вийшло б
# file:////… — svn таке ковтає при checkout, але svn info віддає канонічні три
# слеші, і порівняння URL у probe() каже «тут інший проєкт».
url = "file:///" + repo.replace("\\", "/").lstrip("/")


def run(args, cwd, tf=None):
    cmd = [sc.SVN] + args + ["--non-interactive"]
    if tf:
        cmd += ["--targets", tf]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True,
                       creationflags=0x08000000, stdin=subprocess.DEVNULL)
    return r.returncode, (sc._dec(r.stderr) + sc._dec(r.stdout)).strip()[:110].replace("\n", " | ")


def targets(lines):
    fd, t = tempfile.mkstemp(suffix=".txt"); os.close(fd)
    with open(t, "w", encoding=ACP, newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return t


def sname(p):
    return sc._short(p)


def fresh():
    wc = os.path.join(base, "wc%d" % fresh.n); fresh.n += 1
    os.makedirs(wc)
    run(["checkout", url, "."], wc)
    return wc
fresh.n = 0

# підготовка: покласти файл у репозиторій
wc0 = fresh()
open(os.path.join(wc0, NAME), "w", encoding="utf-8").write("зміст")
s = sname(os.path.join(wc0, NAME))
print("8.3 поки файл є:", repr(os.path.basename(s) if s else None))
print(run(["add"], wc0, targets([os.path.basename(s)])))
print(run(["commit", "-m", "add", "--force-log"], wc0, targets([os.path.basename(s)])))
print()

print("=" * 66)
print("A. класика: svn delete (файл зникає) -> commit")
print("=" * 66)
wcA = fresh()
sA = os.path.basename(sname(os.path.join(wcA, NAME)))
print("  delete   :", run(["delete"], wcA, targets([sA])))
print("  файл на диску:", os.path.exists(os.path.join(wcA, NAME)))
print("  8.3 тепер:", repr(sname(os.path.join(wcA, NAME))))
print("  commit(старий 8.3):", run(["commit", "-m", "d", "--force-log"], wcA, targets([sA])))

print()
print("=" * 66)
print("B. svn delete --keep-local (файл лишається) -> commit")
print("=" * 66)
wcB = fresh()
sB = os.path.basename(sname(os.path.join(wcB, NAME)))
print("  delete --keep-local:", run(["delete", "--keep-local"], wcB, targets([sB])))
print("  файл на диску:", os.path.exists(os.path.join(wcB, NAME)))
print("  commit:", run(["commit", "-m", "d", "--force-log"], wcB, targets([sB])))

print()
print("=" * 66)
print("C. файла вже нема (як у 'missing') -> підставний файл заради 8.3")
print("=" * 66)
wcC = fresh()
os.unlink(os.path.join(wcC, NAME))                       # людина стерла в Провіднику
print("  8.3 без файла:", repr(sname(os.path.join(wcC, NAME))))
open(os.path.join(wcC, NAME), "w").write("")             # підставний, щоб зʼявився 8.3
sC = os.path.basename(sname(os.path.join(wcC, NAME)))
print("  8.3 з підставним:", repr(sC))
print("  delete --keep-local --force:", run(["delete", "--keep-local", "--force"], wcC, targets([sC])))
print("  commit:", run(["commit", "-m", "d", "--force-log"], wcC, targets([sC])))
print("  прибрали підставний:", (os.unlink(os.path.join(wcC, NAME)), True)[1]
      if os.path.exists(os.path.join(wcC, NAME)) else "вже нема")

shutil.rmtree(base, ignore_errors=True)
