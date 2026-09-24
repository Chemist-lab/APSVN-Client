#!/bin/bash
# Зібрати ПЕРЕНОСНИЙ Python для APSVN.app:  ./make_runtime_mac.sh
#
# Результат — тека runtime-mac/, яку package_mac.sh кладе в .app. Це macOS-двійник
# теки runtime/ на Windows (там це Python embeddable з python.org), і так само як
# вона — не в git, а в збірці: бінарники цілими файлами git тільки роздують.
#
# НАВІЩО. Без цього .app позичав системний python3, і ламалося одразу двоє:
#   * Finder дає застосунку мінімальний PATH, де python3 — це Apple-івський 3.9,
#     а vendor зібрано під 3.14. Подвійний клік помирав на імпорті;
#   * навіть коли python знаходився, він re-exec'иться через власний Python.app,
#     і LaunchServices зараховувала ЙОГО bundle: у Dock писало «Python».
# Обидва лікуються тим самим — своїм Python усередині .app.
#
# ЧОМУ САМЕ ФРЕЙМВОРК З python.org. Він самодостатній: власний OpenSSL лежить
# усередині, у Versions/X.Y/lib. Збірка з Homebrew тягнеться в /opt/homebrew за
# openssl і рештою, тобто переносити довелося б пів-Homebrew.
#
# Чого тут немає: py2app, pyinstaller, python-build-standalone. Перші два тягнуть
# свою модель збірки, третій — качати чужий бінарник по мережі під час збірки.
# Те, що треба, робиться cp, install_name_tool і codesign.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SRC_DIR/runtime-mac"

# Джерело можна підмінити: PYFW=/шлях/до/Python.framework/Versions/3.14
FW="${PYFW:-}"
if [ -z "$FW" ]; then
  for v in $(ls -1 /Library/Frameworks/Python.framework/Versions 2>/dev/null \
             | grep -E '^3\.[0-9]+$' | sort -Vr); do
    FW="/Library/Frameworks/Python.framework/Versions/$v"; break
  done
fi
if [ -z "$FW" ] || [ ! -x "$FW/Python" ]; then
  echo "не знайшов фреймворк Python з python.org." >&2
  echo "Постав його з python.org (не Homebrew — той не самодостатній)," >&2
  echo "або вкажи свій:  PYFW=/шлях/Python.framework/Versions/3.14 $0" >&2
  exit 1
fi
VER="$(basename "$FW")"
echo "джерело: $FW"

# --- ABI: vendor мусить збігатися з цим Python -------------------------------
# Саме на цьому все й горіло: vendor під 3.14, а запускався 3.9. Скомпільований
# _objc.so від однієї мінорної версії в іншу не вантажиться взагалі, і виглядає
# це як «програма не запускається», а не як «не та версія».
TAG="cpython-${VER/./}"
if [ -d "$SRC_DIR/vendor" ]; then
  if ! ls "$SRC_DIR"/vendor/objc/*.so >/dev/null 2>&1; then
    echo "УВАГА: у vendor немає скомпільованого PyObjC — чи туди ставили?" >&2
  elif ! ls "$SRC_DIR"/vendor/objc/*"$TAG"*.so >/dev/null 2>&1; then
    echo "СТОП: vendor зібрано НЕ під $VER (шукав $TAG у vendor/objc/*.so)." >&2
    echo "Перестав його тим самим Python:" >&2
    echo "  $FW/bin/python3 -m pip install --target vendor pywebview \\" >&2
    echo "      pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit keyring" >&2
    exit 1
  fi
fi

rm -rf "$OUT"
mkdir -p "$OUT/Python.framework/Versions"
DST="$OUT/Python.framework/Versions/$VER"

echo "копіюю (це найдовше)..."
cp -R "$FW" "$DST"
chmod -R u+w "$DST"

# Фреймворк має виглядати як фреймворк, інакше codesign сперечається.
ln -sfn "$VER" "$OUT/Python.framework/Versions/Current"
ln -sfn "Versions/Current/Python" "$OUT/Python.framework/Python"
[ -d "$DST/Resources" ] && ln -sfn "Versions/Current/Resources" "$OUT/Python.framework/Resources"

# --- обрізання ---------------------------------------------------------------
# Художникові не потрібні ні тести CPython, ні документація, ні Tk: інтерфейс
# APSVN — це WKWebView. Лишається те, без чого програма не підніметься.
L="$DST/lib/python$VER"
rm -rf "$DST/Resources/English.lproj" "$DST/Frameworks" "$DST/include" \
       "$DST/share" "$DST/Headers" "$DST/bin" "$DST/_CodeSignature" \
       "$L/test" "$L/idlelib" "$L/tkinter" "$L/turtledemo" "$L/ensurepip" \
       "$L/lib2to3" "$L/config-$VER-darwin" "$L/site-packages" \
       "$DST/lib/pkgconfig" 2>/dev/null || true
mkdir -p "$L/site-packages"
rm -f "$DST"/lib/*.a
rm -f "$L"/lib-dynload/_tkinter*.so "$L"/lib-dynload/_test*.so \
      "$L"/lib-dynload/xx*.so "$L"/lib-dynload/_ctypes_test*.so 2>/dev/null || true

# Стаб-виконуваний: саме він дає застосунку власну особу в Dock. Береться з
# Resources/Python.app — це той бінарник, який python.org кладе для програм з
# інтерфейсом; звичайний bin/python3 для цього не призначений.
cp "$FW/Resources/Python.app/Contents/MacOS/Python" "$OUT/python3"
chmod u+w,+x "$OUT/python3"
rm -rf "$DST/Resources/Python.app"

# --- переносність ------------------------------------------------------------
# Усі посилання всередині фреймворку стають відносними до самого файлу
# (@loader_path), а стаб шукає фреймворк відносно себе (@executable_path).
# Абсолютний шлях лишити не можна: на машині художника /Library/Frameworks
# порожня, і .so просто не завантажиться.
python3 - "$OUT" "$FW" "$VER" <<'PY'
import os, subprocess, sys

out, src, ver = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
root = os.path.join(out, "Python.framework", "Versions", ver)
stub = os.path.join(out, "python3")

def macho(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(4) in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
                                  b"\xce\xfa\xed\xfe")
    except OSError:
        return False

def deps(path):
    o = subprocess.run(["otool", "-L", path], capture_output=True, text=True)
    return [l.split(" (")[0].strip() for l in o.stdout.splitlines()[1:] if l.strip()]

targets = [stub]
for base, _, names in os.walk(root):
    for n in names:
        p = os.path.join(base, n)
        if not os.path.islink(p) and macho(p):
            targets.append(p)

changed = 0
for path in targets:
    # Куди веде абсолютне посилання, якщо перекласти його в нову теку.
    for dep in deps(path):
        if not dep.startswith(src + "/"):
            continue
        tgt = os.path.join(root, dep[len(src) + 1:])
        if path == stub:
            rel = os.path.relpath(tgt, root)
            new = "@executable_path/../Frameworks/Python.framework/Versions/%s/%s" % (ver, rel)
        else:
            new = "@loader_path/" + os.path.relpath(tgt, os.path.dirname(path))
        subprocess.run(["install_name_tool", "-change", dep, new, path],
                       capture_output=True)
        changed += 1
    # Власне імʼя теж не має бути абсолютним.
    o = subprocess.run(["otool", "-D", path], capture_output=True, text=True)
    lines = [l.strip() for l in o.stdout.splitlines()[1:] if l.strip()]
    if lines and lines[0].startswith(src + "/"):
        tgt = os.path.join(root, lines[0][len(src) + 1:])
        subprocess.run(["install_name_tool", "-id",
                        "@loader_path/" + os.path.basename(tgt), path],
                       capture_output=True)
        changed += 1

print("  переписано посилань: %d у %d файлах" % (changed, len(targets)))

left = []
for path in targets:
    if any(d.startswith(src + "/") for d in deps(path)):
        left.append(path)
if left:
    print("  СТОП: абсолютні посилання лишилися у:", *left[:5], sep="\n    ")
    sys.exit(1)
PY

# --- байт-код стандартної бібліотеки -----------------------------------------
# Робимо його hash-based unchecked (PEP 552), і причина конкретна: cp -R міняє
# час зміни .py, а звичайний .pyc звіряється саме за часом — тобто одразу після
# копіювання ВСЯ бібліотека вважається застарілою. Далі одне з двох, і обидва
# погані: або Python перепише .pyc і зламає пломбу підпису просто в художника,
# або (з PYTHONDONTWRITEBYTECODE, як у нас) компілюватиме її наново щоразу, і
# кожен запуск буде довшим. unchecked-hash не звіряється ні з часом, ні з
# хешем — він просто береться, і копіювання йому байдуже.
echo "компілюю стандартну бібліотеку..."
"$FW/bin/python3" -m compileall -q -f --invalidation-mode unchecked-hash "$L" \
  >/dev/null 2>&1 || true

# --- підпис ------------------------------------------------------------------
# install_name_tool ламає підпис кожного зміненого Mach-O, а на Apple Silicon
# бінарник із побитим підписом не «попереджає», а не запускається.
echo "підписую..."
find "$OUT" -type f \( -name "*.dylib" -o -name "*.so" -o -name "Python" \
     -o -name "python3" \) -print0 \
  | xargs -0 -n1 codesign --force --sign - 2>/dev/null || true
codesign --force --sign - "$OUT/Python.framework" 2>/dev/null || true

echo
echo "готово: $OUT  ($(du -sh "$OUT" | cut -f1))"
echo "package_mac.sh підхопить її сам."
