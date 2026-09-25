# -*- coding: utf-8 -*-
"""Дослід: як поводиться `svn move` — щоб перенесення в провіднику спиралося на
побачене, а не на документацію.

Питання:
 1. що каже `svn status --xml` про обидві половини переносу;
 2. чи можна здати лише одну половину;
 3. як назвати в --targets джерело, якого вже немає на диску, коли в імені
    символ поза кодовою сторінкою (апостроф U+02BC);
 4. чи повертає `svn move` назад «як було»;
 5. що буде з переносом у теку, якої svn ще не знає;
 6. лок: перенесення файлу, який тримаєш сам.
"""
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "app"))
import svn_client as sc

base = tempfile.mkdtemp(prefix="apsvn_mv_")
repo = os.path.join(base, "repo")
subprocess.run([sc.SVNADMIN, "create", repo], check=True, capture_output=True)
url = "file:///" + repo.replace(os.sep, "/").lstrip("/")
wc = os.path.join(base, "wc")
sc.checkout(url, wc)


def put(rel, data=b"x"):
    full = os.path.join(wc, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data)


def raw_status():
    return sc._dec(sc._run(["status", ".", "--xml"], cwd=wc))


def svn(*args):
    try:
        return "OK  " + sc._dec(sc._run(list(args), cwd=wc)).strip()[:300]
    except sc.SvnError as e:
        return "ERR " + (e.raw or str(e)).strip()[:400]


APO = "сценаʼдругa.blend"          # апостроф поза будь-якою ANSI
put("Кадри/сцена.blend", b"BLEND1")
put("Кадри/" + APO, b"BLEND2")
put("Текстури/wood.png", b"PNG")
os.makedirs(os.path.join(wc, "Архів"))
sc.add(wc, ["Кадри", "Текстури", "Архів"])
print("seed:", sc.commit(wc, ["Кадри", "Текстури", "Архів"], "seed"))

print("\n=== 1. перенос файлу в теку (кирилиця, 8.3 в argv) ===")
src = os.path.join(wc, "Кадри", "сцена.blend")
dst = os.path.join(wc, "Архів")
print("ascii src:", sc._ascii_path(src), "| ascii dst:", sc._ascii_path(dst))
print(svn("move", sc._ascii_path(src), sc._ascii_path(dst)))
print(raw_status())
print("на диску:", os.listdir(os.path.join(wc, "Архів")),
      os.path.exists(src))

print("\n=== 2. здати лише нову половину ===")
print(svn("commit", "-m", "half", "--targets",
          sc._targets_file(["Архів/сцена.blend"], wc)))
print("=== 2б. обидві половини ===")
print(svn("commit", "-m", "both", "--targets",
          sc._targets_file(["Архів/сцена.blend", "Кадри/сцена.blend"], wc)))
print(raw_status())

print("\n=== 3. джерело з U+02BC, якого вже нема на диску ===")
src2 = os.path.join(wc, "Кадри", APO)
print("ascii src2:", sc._ascii_path(src2))
print(svn("move", sc._ascii_path(src2), sc._ascii_path(dst)))
print(raw_status())
try:
    print("targets без заглушки:",
          sc._targets_file(["Архів/" + APO, "Кадри/" + APO], wc))
except sc.SvnError as e:
    print("targets без заглушки: ERR", e)
ph = src2
open(ph, "wb").close()                       # заглушка — щоб з'явився 8.3
print("зі заглушкою, статус:")
print(raw_status())
try:
    tf = sc._targets_file(["Архів/" + APO, "Кадри/" + APO], wc)
    print(open(tf, encoding="latin-1").read())
    print(svn("commit", "-m", "apostrophe move", "--targets", tf))
except sc.SvnError as e:
    print("ERR", e)
print("після коміту заглушка на диску:", os.path.exists(ph))
print(raw_status())
if os.path.exists(ph):
    os.unlink(ph)

print("\n=== 4. перенести і повернути назад ===")
w = os.path.join(wc, "Текстури", "wood.png")
print(svn("move", sc._ascii_path(w), sc._ascii_path(dst)))
back = os.path.join(wc, "Архів", "wood.png")
print(svn("move", sc._ascii_path(back), sc._ascii_path(os.path.join(wc, "Текстури"))))
print("статус після повернення:")
print(raw_status())

print("\n=== 4б. перенести, змінити, повернути ===")
print(svn("move", sc._ascii_path(w), sc._ascii_path(dst)))
os.chmod(back, 0o666)
with open(back, "wb") as fh:
    fh.write(b"PNG changed after move")
print(svn("move", sc._ascii_path(back), sc._ascii_path(os.path.join(wc, "Текстури"))))
print(raw_status())
print("вміст повернутого:", open(w, "rb").read())
print(svn("revert", "--depth", "infinity", "--targets", sc._targets_file(["Текстури/wood.png"], wc)))

print("\n=== 5. у теку, якої svn не знає ===")
os.makedirs(os.path.join(wc, "Нова"))
print(svn("move", sc._ascii_path(w), sc._ascii_path(os.path.join(wc, "Нова"))))
print(svn("add", "--depth", "empty", sc._ascii_path(os.path.join(wc, "Нова"))))
print(svn("move", sc._ascii_path(w), sc._ascii_path(os.path.join(wc, "Нова"))))
print(raw_status())
print(svn("revert", "--depth", "infinity", "--targets",
          sc._targets_file(["Текстури/wood.png", "Нова/wood.png", "Нова"], wc)))
for leftover in ("Нова",):
    shutil.rmtree(os.path.join(wc, leftover), ignore_errors=True)
print("після revert:", raw_status())

print("\n=== 6. лок: перенести файл, який тримаю сам ===")
print(svn("lock", "--targets", sc._targets_file(["Текстури/wood.png"], wc)))
print(svn("move", sc._ascii_path(w), sc._ascii_path(dst)))
print(raw_status())
print(svn("commit", "-m", "move locked", "--targets",
          sc._targets_file(["Архів/wood.png", "Текстури/wood.png"], wc)))
print(raw_status())
print("лок на новому місці:", svn("info", "--show-item", "lock-owner",
                                  sc._ascii_path(os.path.join(wc, "Архів", "wood.png"))))

print("\n=== 7. перенос теки ===")
put("Кадри/sh010/a.blend", b"A")
sc.add(wc, ["Кадри/sh010"])
sc.commit(wc, ["Кадри/sh010"], "sh010")
print(svn("move", sc._ascii_path(os.path.join(wc, "Кадри", "sh010")), sc._ascii_path(dst)))
print(raw_status())

shutil.rmtree(base, ignore_errors=True)
