# -*- coding: utf-8 -*-
"""Оновлення програми — включно з підміною теки, яку роблять по-справжньому.

Найризикованіша частина всього проєкту: помилка тут не псує один файл, а
лишає художника без працездатної програми. Тому підміна тут не «перевіряється
на око», а ганяється цілком — у пісочниці, зі справжнім сценарієм, справжнім
перейменуванням тек і справжнім перезапуском.

Мережа тут не потрібна: завантаження перевіряється через file://, а реліз
підробляється звичайним zip.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import desktop
import updater as up

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" | " + str(detail) if detail else ""))


ROOT = tempfile.mkdtemp(prefix="apsvn_upd_")


def build_zip(path, root_name="APSVN", extra=None, complete=True):
    """Підробити архів релізу."""
    with zipfile.ZipFile(path, "w") as z:
        if complete:
            z.writestr("%s/app.py" % root_name, "VERSION = \"9.9.9\"\n")
            z.writestr("%s/svn_client.py" % root_name, "# svn\n")
            z.writestr("%s/ui/index.html" % root_name, "<html>new</html>")
        z.writestr("%s/marker.txt" % root_name, "new build")
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return path


print("=" * 66)
print("1. Порівняння версій")
print("=" * 66)
check("новіша розпізнається", up.newer("v1.1.0", "1.0.0"))
check("однакові — не новіша", not up.newer("1.0.0", "1.0.0"))
check("старіша — не новіша", not up.newer("0.9", "1.0.0"))
# Класична пастка: як рядки "1.9" більше за "1.10", і оновлення тихо
# перестало б пропонуватись рівно тоді, коли версій стане більше десяти.
check("1.10 новіша за 1.9 (а не навпаки)", up.newer("1.10", "1.9"))
check("і 1.9 не новіша за 1.10", not up.newer("1.9", "1.10"))
check("різна довжина: 2 > 1.99.99", up.newer("v2", "1.99.99"))
check("сміття не валить", up.newer("", "1.0.0") is False)

print()
print("=" * 66)
print("2. Який файл брати з релізу")
print("=" * 66)
assets = [{"name": "APSVN-1.1.0.zip", "size": 1, "browser_download_url": "w"},
          {"name": "APSVN-1.1.0-mac.zip", "size": 2, "browser_download_url": "m"},
          {"name": "README.md", "size": 3, "browser_download_url": "r"}]
had = (desktop.WINDOWS, desktop.MAC)
desktop.WINDOWS, desktop.MAC = True, False
check("на Windows — не маківський", up._asset_for(assets)["name"] == "APSVN-1.1.0.zip")
desktop.WINDOWS, desktop.MAC = False, True
check("на маку — маківський", up._asset_for(assets)["name"] == "APSVN-1.1.0-mac.zip")
desktop.WINDOWS, desktop.MAC = had
check("не-zip ігнорується", up._asset_for([{"name": "notes.txt"}]) is None)
check("порожній реліз не валить", up._asset_for([]) is None)

print()
print("=" * 66)
print("3. Розпакування й перевірка, що це справді APSVN")
print("=" * 66)
zp = build_zip(os.path.join(ROOT, "good.zip"))
root = up.stage(zp, os.path.join(ROOT, "stage1"))
check("знайшов корінь усередині архіву",
      os.path.isfile(os.path.join(root, "app.py")), root)
check("розпакував усе", os.path.isfile(os.path.join(root, "ui", "index.html")))

zp2 = build_zip(os.path.join(ROOT, "bad.zip"), complete=False)
try:
    up.stage(zp2, os.path.join(ROOT, "stage2"))
    check("чужий архів відхиляється", False, "прийнято, а не мало")
except IOError as e:
    check("чужий архів відхиляється", "does not look like" in str(e), e)

# Архів, що намагається писати поза текою — класична zip-slip. Ціна помилки
# тут не «не оновилось», а «переписало щось у системі».
evil = os.path.join(ROOT, "evil.zip")
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("APSVN/app.py", "x")
    z.writestr("../../pwned.txt", "x")
try:
    up.stage(evil, os.path.join(ROOT, "stage3"))
    check("архів із виходом за межі теки відхиляється", False, "прийнято")
except IOError as e:
    check("архів із виходом за межі теки відхиляється",
          "outside" in str(e), e)

print()
print("=" * 66)
print("4. Завантаження: обрізане не приймається")
print("=" * 66)
src = os.path.join(ROOT, "src.bin")
io.open(src, "wb").write(b"A" * 5000)
url = "file:///" + src.replace(os.sep, "/")
seen = []
dst = up.download(url, os.path.join(ROOT, "got.bin"), size=5000,
                  progress=lambda g, t: seen.append((g, t)))
check("файл завантажено", os.path.getsize(dst) == 5000)
check("поступ повідомлявся", len(seen) > 0, seen[:2])
check("тимчасового .part не лишилось", not os.path.exists(dst + ".part"))

try:
    up.download(url, os.path.join(ROOT, "short.bin"), size=999999)
    check("невідповідність розміру ловиться", False, "прийнято")
except IOError as e:
    check("невідповідність розміру ловиться", "expected" in str(e), e)
check("і обрізок не лишився на диску",
      not os.path.exists(os.path.join(ROOT, "short.bin.part")))

print()
print("=" * 66)
print("5. ПІДМІНА ТЕКИ — по-справжньому")
print("=" * 66)
# Будуємо «встановлену програму», «нову збірку» поруч, і проганяємо той самий
# сценарій, який запускатиметься у художника.
install = os.path.join(ROOT, "APSVN")
os.makedirs(os.path.join(install, "ui"))
io.open(os.path.join(install, "app.py"), "w").write("VERSION = \"1.0.0\"")
io.open(os.path.join(install, "marker.txt"), "w").write("old build")
io.open(os.path.join(install, "ui", "index.html"), "w").write("<html>old</html>")

staged = up.stage(build_zip(os.path.join(ROOT, "new.zip")),
                  os.path.join(ROOT, "staged"))
work = os.path.join(ROOT, "work")
os.makedirs(work, exist_ok=True)

# «Перезапуск» — сценарій, який лишає слід, щоб було видно, що його покликали
done = os.path.join(ROOT, "relaunched.txt")
if desktop.WINDOWS:
    relaunch = os.path.join(ROOT, "relaunch.bat")
    io.open(relaunch, "w", newline="\r\n").write(
        "@echo off\r\necho yes> \"%s\"\r\n" % done)
elif desktop.MAC:
    # На маку в сценарії підміни стоїть `open`, і це правильно: там relaunch —
    # то APSVN.app. Але `open` не ВИКОНУЄ файл, він відкриває його тим, чим
    # система вважає за потрібне, тож звичайний .sh просто поїхав би в
    # редактор. Підробка мусить бути справжнім bundle, інакше перевірка міряє
    # не те, що станеться в художника.
    relaunch = os.path.join(ROOT, "Relaunch.app")
    os.makedirs(os.path.join(relaunch, "Contents", "MacOS"))
    io.open(os.path.join(relaunch, "Contents", "Info.plist"), "w").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict>'
        '<key>CFBundleName</key><string>Relaunch</string>'
        '<key>CFBundleIdentifier</key><string>cloud.altpicture.relaunchtest</string>'
        '<key>CFBundleExecutable</key><string>Relaunch</string>'
        '<key>CFBundlePackageType</key><string>APPL</string>'
        '</dict></plist>\n')
    exe = os.path.join(relaunch, "Contents", "MacOS", "Relaunch")
    io.open(exe, "w", newline="\n").write(
        "#!/bin/bash\necho yes > '%s'\n" % done)
    os.chmod(exe, 0o755)
else:
    relaunch = os.path.join(ROOT, "relaunch.sh")
    io.open(relaunch, "w", newline="\n").write(
        "#!/bin/bash\necho yes > '%s'\n" % done)
    os.chmod(relaunch, 0o755)

# PID, якого точно немає: сценарій має одразу побачити, що чекати нема кого.
dead_pid = 999999
script = up.write_swap_script(work, staged, install, dead_pid, relaunch)
check("сценарій підміни створено", os.path.isfile(script), script)
# Генерований сценарій мусить бути ASCII: консольна cp866 не має ні «і», ні
# «ї», ні «є» — один український коментар, і оновлення падає на останньому
# кроці, вже після того, як усе завантажено.
raw = io.open(script, "rb").read()
check("сценарій суцільно ASCII", all(b < 128 for b in raw),
      [b for b in raw if b >= 128][:5])
body = io.open(script, encoding="utf-8").read()
check("він чекає саме на наш процес", str(dead_pid) in body)
check("він перейменовує стару теку, а не видаляє її одразу",
      ".old-" in body)

up.launch_detached(script)

# Чекаємо на результат — але не вічно
for _ in range(60):
    if os.path.exists(done):
        break
    time.sleep(0.5)
time.sleep(1.0)

check("нова збірка стала на місце старої",
      io.open(os.path.join(install, "marker.txt")).read().strip() == "new build",
      io.open(os.path.join(install, "marker.txt")).read().strip()
      if os.path.exists(os.path.join(install, "marker.txt")) else "теки немає")
check("вміст оновився і в підтеках",
      "new" in io.open(os.path.join(install, "ui", "index.html")).read())
check("програму перезапущено", os.path.exists(done))
leftovers = [d for d in os.listdir(ROOT) if ".old-" in d]
check("стару теку прибрано після успіху", not leftovers, leftovers)

print()
print("=" * 66)
print("6. Мережа: check() ніколи не кидає")
print("=" * 66)
# Художник у поїзді. Це не привід валити програму.
saved = up.API
up.API = "http://127.0.0.1:9/nope"
r = up.check("1.0.0")
check("немає зв'язку -> стан offline, а не виняток",
      r["state"] in ("offline", "error"), r)
check("і посилання на сторінку релізів усе одно є", r.get("url"), r)
up.API = saved

# python.org збирає Python із власним OpenSSL, і той іде БЕЗ кореневих
# сертифікатів, доки не запустять «Install Certificates.command». Тоді жоден
# https із Python не працює, і ця перевірка міряла б стан машини, а не код. У
# самій збірці питання не стоїть: корені їдуть у комплекті (svn/cert.pem), і
# svn_client показує на них через SSL_CERT_FILE — перевірено, Python їх бачить.
import ssl as _ssl
try:
    _roots = len(_ssl.create_default_context().get_ca_certs())
except Exception:
    _roots = 0
r = up.check("1.0.0")
if _roots or r["state"] in ("ok", "none"):
    check("живий сервер відповідає", r["state"] in ("ok", "none"), r)
else:
    check("живий сервер відповідає (цей Python без коренів — нічим перевіряти)",
          r["state"] == "offline", r)
check("«релізів ще немає» — це стан none, а не поламка",
      r["state"] != "error", r)

shutil.rmtree(ROOT, ignore_errors=True)
print()
print("=" * 66)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 66)
sys.exit(1 if FAIL else 0)
