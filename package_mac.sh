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
"$PY" -c 'import webview, objc, keyring' 2>/dev/null || {
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

# --- запускач ----------------------------------------------------------------
# Окремий скрипт, а не прямий виклик python: у .app виконуваний файл мусить
# бути один і лежати саме в MacOS/, а Python треба ще й показати, де vendor.
cat > "$APP/Contents/MacOS/$APP_NAME" <<'LAUNCH'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PYTHONPATH="$DIR:$DIR/vendor:${PYTHONPATH:-}"
exec "${PYTHON:-python3}" "$DIR/app.py" "$@"
LAUNCH
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
