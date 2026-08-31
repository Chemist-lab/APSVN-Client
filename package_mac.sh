#!/bin/bash
# Зібрати APSVN.app. Запускати НА МАКУ, з теки проєкту:  ./package_mac.sh
#
# Нотаризації тут немає навмисно: вона потребує Developer ID за $99/рік. Без
# неї програма працює так само, але при першому запуску macOS її притримає —
# див. підказку в кінці. Ad-hoc підпис нижче — це ІНШЕ й безкоштовне: на
# Apple Silicon непідписаний бінарник не «попереджає», а просто не
# запускається, тож без нього збірка була б мертвою.
#
# Чого тут НЕМАЄ і чому:
#   * py2app / briefcase — тягнуть свою модель збірки й купу залежностей
#     заради того, що тут робиться тридцятьма рядками cp і plist;
#   * власного Python — див. RUNTIME нижче.
set -euo pipefail

APP_NAME="APSVN"
SRC="$(cd "$(dirname "$0")" && pwd)"
OUT="$SRC/dist"
APP="$OUT/$APP_NAME.app"
VER="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC/app.py")"

if [ -z "$VER" ]; then
  echo "не знайшов VERSION в app.py" >&2
  exit 1
fi
echo "$APP_NAME $VER"

# --- перевірки, які дешевше зробити зараз, ніж у художника ------------------
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "немає python3" >&2; exit 1; }
# PYTHONPATH саме такий, як у запускачі нижче: залежності лежать у vendor, а
# не в системному python, і без цього перевірка лаялась на цілком справну
# збірку — а тоді її просто перестають читати.
PYTHONPATH="$SRC/vendor" "$PY" -c 'import webview, objc, keyring' 2>/dev/null || {
  echo "бракує залежностей. Постав їх у теку vendor:" >&2
  echo "  $PY -m pip install --target vendor pywebview pyobjc-core \\" >&2
  echo "      pyobjc-framework-Cocoa pyobjc-framework-WebKit keyring" >&2
}
command -v svn >/dev/null || echo "УВАГА: svn у PATH немає (brew install svn)" >&2

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# --- код --------------------------------------------------------------------
for f in app.py svn_client.py explorer.py desktop.py shellicon.py \
         shellicon_mac.py blendthumb.py imgthumb.py; do
  cp "$SRC/$f" "$APP/Contents/Resources/"
done
cp -R "$SRC/ui" "$APP/Contents/Resources/"
[ -d "$SRC/vendor" ] && cp -R "$SRC/vendor" "$APP/Contents/Resources/"

# shellicon_win.py не кладемо: на маку він не імпортується ніколи, а тягнути
# в збірку код для чужої системи означає лише збивати з пантелику того, хто
# полізе всередину.

# --- svn ---------------------------------------------------------------------
# Свій svn у комплекті кращий за системний: чужий може бути старим або
# зібраним без serf, тобто без https, і з'ясується це в художника під час
# першої ж дії. Але svn з Homebrew НЕ ПЕРЕНОСНИЙ як є — він лінкується на
# /opt/homebrew/lib/*.dylib. Робити його переносним (install_name_tool + rpath)
# — окрема робота; поки що покладаємось на системний і чесно про це кажемо.
if [ -d "$SRC/svn-mac" ]; then
  cp -R "$SRC/svn-mac" "$APP/Contents/Resources/svn"
  echo "  svn: узято з svn-mac/"
else
  echo "  svn: свого немає, покладаємось на системний ($(command -v svn || echo 'НЕ ЗНАЙДЕНО'))"
fi

# --- свій Python -------------------------------------------------------------
# runtime-mac/ робить make_runtime_mac.sh. Це двійник теки runtime/ на Windows:
# без неї .app позичає системний python (див. довгий коментар у запускачі),
# з нею — художник не встановлює нічого, і в Dock написано APSVN, а не Python.
RUNTIME=""
if [ -d "$SRC/runtime-mac/Python.framework" ] && [ -x "$SRC/runtime-mac/python3" ]; then
  mkdir -p "$APP/Contents/Frameworks"
  cp -R "$SRC/runtime-mac/Python.framework" "$APP/Contents/Frameworks/"
  cp "$SRC/runtime-mac/python3" "$APP/Contents/MacOS/python3"
  chmod +x "$APP/Contents/MacOS/python3"
  RUNTIME="$(ls -1 "$APP/Contents/Frameworks/Python.framework/Versions" \
             | grep -E '^3\.[0-9]+$' | sort -Vr | head -1)"
  echo "  python: свій, $RUNTIME (у Contents/Frameworks)"
else
  echo "  python: свого немає, покладаємось на системний — ./make_runtime_mac.sh" >&2
fi

# --- запускач ----------------------------------------------------------------
# Окремий скрипт, а не прямий виклик python: у .app виконуваний файл мусить
# бути один і лежати саме в MacOS/, а Python треба ще й показати, де vendor.
#
# ТУТ БУЛА МІНА, і вона коштувала б кожного першого запуску. Раніше стояло
# просто exec "${PYTHON:-python3}". З термінала це працює — там у PATH перший
# той python, яким ставили vendor. Але Finder дає програмі МІНІМАЛЬНИЙ PATH
# (/usr/bin:/bin:/usr/sbin:/sbin), де python3 — це Apple-івський /usr/bin/python3
# версії 3.9. А vendor зібрано під 3.14: скомпільований _objc.so просто не
# вантажиться в 3.9, і програма вмирала на імпорті ще до першого вікна. Тобто
# збірка, яку розробник щойно перевірив у себе, у художника не піднімалася б
# зовсім — а перевірка «python3 app.py» цього не показує НІКОЛИ.
#
# Тому питаємо не версію, а саму придатність: чи вміє цей python підняти те,
# що лежить у vendor. Версію можна вгадати неправильно, імпорт — ні. Ця гілка
# лишається запасною: коли рантайм у комплекті, шукати нема чого.
if [ -n "$RUNTIME" ]; then

# Свій Python — і саме тому exec іде в бінарник УСЕРЕДИНІ нашого bundle. Це не
# дрібниця: коли запускали системний, він re-exec'ився через власний Python.app,
# і LaunchServices зараховувала той bundle — у Dock писало «Python», іконка й
# назва були чужі. Достатньо, щоб виконуваний файл лежав у наших Contents/MacOS,
# і застосунок стає собою: cloud.altpicture.apsvn.
#
# PYTHONHOME задаємо явно. Стаб узятий з Python.app усередині фреймворку, а
# лежить тепер у Contents/MacOS — тобто орієнтири, за якими CPython сам шукає
# стандартну бібліотеку, з-під нього більше не видно. Вгадувати тут нічого:
# кажемо прямо, де вона.
cat > "$APP/Contents/MacOS/$APP_NAME" <<LAUNCH
#!/bin/bash
HERE="\$(cd "\$(dirname "\$0")" && pwd)"
DIR="\$(cd "\$HERE/../Resources" && pwd)"
export PYTHONHOME="\$HERE/../Frameworks/Python.framework/Versions/$RUNTIME"
export PYTHONPATH="\$DIR:\$DIR/vendor"
export PYTHONDONTWRITEBYTECODE=1
exec "\$HERE/python3" "\$DIR/app.py" "\$@"
LAUNCH

else

cat > "$APP/Contents/MacOS/$APP_NAME" <<'LAUNCH'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PYTHONPATH="$DIR:$DIR/vendor:${PYTHONPATH:-}"
# Без цього перший же запуск клав 174 файли .pyc у 41 теку __pycache__ ВСЕРЕДИНІ
# підписаного bundle і ламав пломбу підпису: codesign після цього каже "a sealed
# resource is missing or invalid". Байт-код кладеться на збірці (нижче), тобто
# під підпис, а в художника вже нічого не дописується.
export PYTHONDONTWRITEBYTECODE=1

usable() {
  [ -n "$1" ] && [ -x "$1" ] &&     "$1" -c 'import webview, objc, keyring' >/dev/null 2>&1
}

CANDS=()
[ -n "${PYTHON:-}" ] && CANDS+=("$PYTHON")
CANDS+=(/opt/homebrew/bin/python3 /usr/local/bin/python3)
# Збірки з python.org — новіші першими, інакше 3.9 обійде 3.14 за абеткою.
while IFS= read -r p; do
  [ -n "$p" ] && CANDS+=("$p")
done < <(ls -d /Library/Frameworks/Python.framework/Versions/*/bin/python3          2>/dev/null | sort -Vr)
CANDS+=("$(command -v python3 2>/dev/null)" /usr/bin/python3)

for py in "${CANDS[@]}"; do
  if usable "$py"; then
    exec "$py" "$DIR/app.py" "$@"
  fi
done

# Жоден не підійшов. Мовчки померти — найгірше з можливого: художник двічі
# клацнув і не сталося нічого. Тож кажемо, що саме не так.
osascript -e 'display dialog "APSVN did not find a Python that can run it.

The application needs Python 3.14 (the version its bundled libraries were built
for). Install it from python.org or with: brew install python

APSVN will start by itself once it is there." with title "APSVN" buttons {"OK"} default button 1 with icon stop' >/dev/null 2>&1
exit 1
LAUNCH

fi
chmod +x "$APP/Contents/MacOS/$APP_NAME"

# --- Info.plist --------------------------------------------------------------
# LSMinimumSystemVersion 11.0: нижче немає сенсу — Apple Silicon починається
# звідти, а на старіших Intel-маках свої правила підпису.
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>cloud.altpicture.apsvn</string>
  <key>CFBundleVersion</key><string>$VER</string>
  <key>CFBundleShortVersionString</key><string>$VER</string>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <!-- Без цього вікно WKWebView не отримує фокус клавіатури -->
  <key>NSPrincipalClass</key><string>NSApplication</string>
</dict>
</plist>
PLIST

# --- байт-код ----------------------------------------------------------------
# Компілюємо ДО підпису: інакше або запуск пише .pyc у bundle і ламає пломбу,
# або (з PYTHONDONTWRITEBYTECODE) кожен старт компілює наново. Якщо в художника
# інша мінорна версія Python, ці .pyc просто ігноруються — це не помилка.
# unchecked-hash з тієї ж причини, що й для бібліотеки в make_runtime_mac.sh:
# байт-код, звірений за часом, не переживає копіювання й розпакування.
PYTHONPATH="$SRC/vendor" "$PY" -m compileall -q -f \
  --invalidation-mode unchecked-hash "$APP/Contents/Resources" \
  >/dev/null 2>&1 || true

# --- ad-hoc підпис -----------------------------------------------------------
# "-" означає ad-hoc: підпис без сертифіката, безкоштовний, акаунта не треба.
# Це НЕ нотаризація і Gatekeeper він не задовольняє — але задовольняє вимогу
# Apple Silicon «усе виконуване має бути підписане», без якої нічого не
# запуститься взагалі.
if command -v codesign >/dev/null; then
  codesign --force --deep --sign - "$APP" 2>/dev/null \
    && echo "  підписано ad-hoc" \
    || echo "  УВАГА: codesign не спрацював — на Apple Silicon не запуститься"
else
  echo "  УВАГА: codesign немає (постав Xcode Command Line Tools)"
fi

# --- архів --------------------------------------------------------------------
# ditto, а не zip: zip губить розширені атрибути й підпис усередині .app
( cd "$OUT" && ditto -c -k --sequesterRsrc --keepParent \
    "$APP_NAME.app" "$APP_NAME-$VER-mac.zip" )

echo
echo "готово: $OUT/$APP_NAME-$VER-mac.zip"
echo
echo "Першого разу macOS не дасть відкрити програму, бо вона не нотаризована."
echo "Художникові треба сказати рівно це:"
echo "  Системні налаштування -> Конфіденційність і безпека ->"
echo "  внизу «$APP_NAME заблоковано» -> «Все одно відкрити»."
echo "Один раз на встановлення."
