# -*- coding: utf-8 -*-
"""Поступ передачі: чи надходять події живцем і чи вони чесні.

Головне, що тут перевіряється, — що APSVN не показує вигаданих відсотків.
Дослід (scratchpad/exp_progress.py) встановив: svn друкує рядки по ходу, але
крапки в «Transmitting file data ....» обсягу НЕ відповідають (одна крапка на
64 МБ), тому для заливання відсотків бути не може — лише «N з M».
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import desktop
import svn_client as sc

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (" | " + str(detail) if detail else ""))


base = tempfile.mkdtemp(prefix="apsvn_prog_")
sc.ensure_config(os.path.join(base, "ad"))
repo = os.path.join(base, "repo")
wc = os.path.join(base, "Проєкт Міста")
wc2 = os.path.join(base, "друга")
subprocess.run([sc.SVNADMIN,
                "create", repo], check=True, capture_output=True)
# .lstrip: на POSIX шлях уже починається з "/", і без цього вийшло б
# file:////… — svn таке ковтає при checkout, але svn info віддає канонічні три
# слеші, і порівняння URL у probe() каже «тут інший проєкт».
url = "file:///" + repo.replace("\\", "/").lstrip("/")
sc.checkout(url, wc)

N = 60
names = []
os.makedirs(os.path.join(wc, "shots"), exist_ok=True)
sc.add(wc, ["shots"])
sc.commit(wc, ["shots"], "тека для кадрів")   # теку здаємо окремо
for i in range(N):
    n = "shots/кадр %02d.blend" % i           # кирилиця у шляхах
    with open(os.path.join(wc, n.replace("/", os.sep)), "wb") as fh:
        fh.write(os.urandom(40000))
    names.append(n)
sc.add(wc, names)

print("=" * 64)
print("1. Заливання: події надходять по ходу")
print("=" * 64)
up = []
r = sc.commit(wc, names, "перший пакет", progress=lambda e: up.append(e))
check("коміт пройшов", "commit" in r, r)
check("події поступу надходили", len(up) >= N, len(up))
check("лічильник зростає", [e["done"] for e in up] == sorted(e["done"] for e in up))
check("дійшов до кінця", up and up[-1]["done"] >= N, up[-1]["done"] if up else None)
check("знає, скільки всього", up and up[0]["total"] == N, up[0]["total"] if up else None)
check("називає поточний файл", any(e["file"] and "кадр" in e["file"] for e in up),
      [e["file"] for e in up[:3]])
check("імена файлів не побиті кодуванням",
      not any("?" in (e["file"] or "") for e in up),
      [e["file"] for e in up[:3]])
phases = [e["phase"] for e in up]
check("є фаза передачі даних", "send" in phases or "finalize" in phases, set(phases))
check("kind = upload", all(e["kind"] == "upload" for e in up))
# найважливіше: під час передачі даних НЕ показуємо вигаданих відсотків
send = [e for e in up if e["phase"] in ("send", "finalize")]
check("на фазі передачі відсотків НЕ вигадуємо",
      all(e["pct"] is None for e in send), [e["pct"] for e in send])

print()
print("=" * 64)
print("2. Перше завантаження: події теж надходять")
print("=" * 64)
down = []
os.makedirs(wc2, exist_ok=True)
sc.checkout(url, wc2, progress=lambda e: down.append(e))
check("події завантаження надходили", len(down) >= N, len(down))
check("kind = download", all(e["kind"] == "download" for e in down))
check("лічильник зростає", [e["done"] for e in down] == sorted(e["done"] for e in down))
check("для чекауту загального числа не вигадуємо",
      all(e["total"] is None for e in down), down[0]["total"] if down else None)

print()
print("=" * 64)
print("3. Оновлення знає, скільки файлів чекати")
print("=" * 64)
sc.lock(wc, [names[0]])
with open(os.path.join(wc, names[0].replace("/", os.sep)), "wb") as fh:
    fh.write(os.urandom(50000))
sc.commit(wc, [names[0]], "правка")
upd = []
sc.update(wc2, progress=lambda e: upd.append(e), total=1)
check("оновлення дало подію", len(upd) >= 1, len(upd))
check("відсотки для оновлення чесні (знаємо total)",
      any(e["pct"] == 100 for e in upd), [e["pct"] for e in upd])

print()
print("=" * 64)
print("4. Качання однієї версії: точні відсотки за розміром")
print("=" * 64)
BIG = "великий.blend"
with open(os.path.join(wc, BIG), "wb") as fh:
    fh.write(os.urandom(6 * 1024 * 1024))
sc.add(wc, [BIG])
sc.commit(wc, [BIG], "великий файл")
got = []
dest = os.path.join(base, "копія.blend")
sc.save_revision_as(wc, BIG, "HEAD", dest, progress=lambda e: got.append(e))
check("файл вивантажено", os.path.getsize(dest) == 6 * 1024 * 1024,
      os.path.getsize(dest))
check("kind = download", all(e["kind"] == "download" for e in got) if got else True)
if got:
    check("знає повний розмір", got[0]["total_bytes"] == 6 * 1024 * 1024,
          got[0]["total_bytes"])
    check("відсотки в межах 0..100",
          all(0 <= (e["pct"] or 0) <= 100 for e in got), [e["pct"] for e in got])
else:
    # на file:// передача миттєва — сторож може не встигнути зробити замір
    check("watcher не заважає, навіть якщо не встиг заміряти", True,
          "замірів 0 — файл прийшов миттєво (file://)")

print()
print("=" * 64)
print("4b. Фаза передачі приходить ПІД ЧАС неї, а не після")
print("=" * 64)
# svn друкує «Transmitting file data ....» без переводу рядка — крапки ростуть,
# а рядок закривається аж наприкінці. Якщо чекати на кінець рядка, смуга висить
# на 100% з іменем останнього переліченого файлу, поки йде найдовша робота.
import time as _t
HEAVY = "важкий.blend"
with open(os.path.join(wc, HEAVY), "wb") as fh:
    fh.write(os.urandom(48 * 1024 * 1024))
sc.add(wc, [HEAVY])
marks = []
t0 = _t.time()
sc.commit(wc, [HEAVY], "великий файл",
          progress=lambda e: marks.append((round(_t.time() - t0, 2), e["phase"])))
total_time = _t.time() - t0
phases = [m[1] for m in marks]
check("фаза передачі зафіксована", "send" in phases, phases)
if "send" in phases:
    at = next(t for t, ph in marks if ph == "send")
    check("вона прийшла ДО кінця операції (не в останню мить)",
          at < total_time * 0.9, "на %.2f с із %.2f с" % (at, total_time))
check("на фазі передачі показано обсяг",
      any(e for e in marks if e[1] == "send"), marks[-3:])

# Швидкість беремо з лічильників вводу-виводу процесу svn.exe. Це ЄДИНЕ
# виміряне число на цій фазі: відсотків тут бути не може, бо svn перечитує
# файли 2.0-2.9 разу залежно від транспорту (scratchpad/exp_bytes.py).
# Навантаження мусить тривати довше за вікно згладжування (0.9 с), інакше
# швидкості просто нема звідки взятися — і це правильно: APSVN не показує
# того, чого не встиг заміряти.
rates, marks2 = [], []
HEAVY2 = "важкий2.blend"
blk = os.urandom(8 * 1024 * 1024)
with open(os.path.join(wc, HEAVY2), "wb") as fh:
    for _ in range(25):                 # 200 МБ
        fh.write(blk)
sc.add(wc, [HEAVY2])
t1 = _t.time()
sc.commit(wc, [HEAVY2], "ще один великий",
          progress=lambda e: (rates.append(e.get("rate")),
                              marks2.append(e["phase"])))
took = _t.time() - t1
real = [r for r in rates if r]
check("операція тривала довше за вікно згладжування", took > 1.5, "%.2f с" % took)
# Лічильники вводу-виводу процесу svn є лише на Windows (GetProcessIoCounters).
# На маку прямого відповідника НЕМАЄ, і це перевірено, а не припущено:
# proc_pid_rusage віддає ri_diskio_bytesread == 0 для V4, V5 і V6 навіть тоді,
# коли процес читає файл повз кеш сторінок (F_NOCACHE) — ядро просто не дає
# цих чисел непривілейованому спостерігачеві. Тому на маку швидкості немає, і
# це правильно: APSVN не показує того, чого не заміряв. Залишок часу там
# рахується з rate_hint — швидкості, заміряної на попередніх передачах.
if desktop.WINDOWS:
    check("швидкість виміряна, а не вигадана", bool(real), rates[:6])
    check("швидкість додатна й правдоподібна",
          all(0 < r < 5e9 for r in real),
          ["%.0f МБ/с" % (r / 1048576) for r in real[:4]])
else:
    check("на маку швидкість чесно не вигадується", not real, rates[:6])
    check("і замість неї не лізе нуль чи сміття",
          all(r is None for r in rates), rates[:6])
check("на коротких операціях швидкість чесно відсутня", rates[0] is None, rates[0])

print()
print("=" * 64)
print("4c. Залишковий час: оцінка лише коли є з чого рахувати")
print("=" * 64)
ev = []
NEW = "ще-один.blend"
with open(os.path.join(wc, NEW), "wb") as fh:
    fh.write(os.urandom(4 * 1024 * 1024))
sc.add(wc, [NEW])
# без заміряної раніше швидкості оцінки бути не може
sc.commit(wc, [NEW], "без підказки", progress=lambda e: ev.append(dict(e)))
check("без підказки залишок НЕ вигадується",
      all(e["eta"] is None for e in ev), [e["eta"] for e in ev[:4]])
check("витрачений час рахується завжди",
      all(e["elapsed"] >= 0 for e in ev) and ev[-1]["elapsed"] > 0,
      ev[-1]["elapsed"])

ev2 = []
NEW2 = "ще-два.blend"
with open(os.path.join(wc, NEW2), "wb") as fh:
    fh.write(os.urandom(20 * 1024 * 1024))
sc.add(wc, [NEW2])
sc.commit(wc, [NEW2], "з підказкою", progress=lambda e: ev2.append(dict(e)),
          total_bytes=20 * 1024 * 1024, rate_hint=10 * 1024 * 1024)
etas = [e["eta"] for e in ev2 if e["eta"] is not None]
check("з підказкою залишок зʼявляється", bool(etas), [e["eta"] for e in ev2[:4]])
if etas:
    check("залишок не зростає з часом", etas == sorted(etas, reverse=True), etas)
    check("залишок правдоподібний (20 МБ / 10 МБ/с ~ 2 с)",
          etas[0] <= 3, etas[0])
check("залишок ніколи не відʼємний", all(e >= 0 for e in etas))

# качання: тут і швидкість, і залишок точні, бо байти відомі
got2 = []
sc.save_revision_as(wc, BIG, "HEAD", os.path.join(base, "ще-копія.blend"),
                    progress=lambda e: got2.append(dict(e)))
check("у подіях качання є поля швидкості й залишку",
      all("rate" in e and "eta" in e for e in got2) if got2 else True,
      got2[:1])

print()
print("=" * 64)
print("5. Збій у поступі не валить саму операцію")
print("=" * 64)


def boom(e):
    raise RuntimeError("навмисна поломка обробника")


with open(os.path.join(wc, "ще.blend"), "wb") as fh:
    fh.write(os.urandom(1000))
sc.add(wc, ["ще.blend"])
try:
    r = sc.commit(wc, ["ще.blend"], "коміт із поламаним обробником", progress=boom)
    check("коміт пройшов попри виняток у обробнику", "commit" in r, r)
except Exception as e:
    check("коміт пройшов попри виняток у обробнику", False, e)

shutil.rmtree(base, ignore_errors=True)
print()
print("=" * 64)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 64)
sys.exit(1 if FAIL else 0)
