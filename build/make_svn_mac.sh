#!/bin/bash
# Зібрати ПЕРЕНОСНИЙ svn для APSVN.app:  ./make_svn_mac.sh
#
# Результат — тека svn-mac/, яку package_mac.sh кладе в .app як Resources/svn.
# Двійник теки svn/ на Windows (там це SlikSvn), і так само не в git.
#
# НАВІЩО. Свій svn у комплекті кращий за системний з тієї ж причини, що й на
# Windows: чужий може бути старим або зібраним без serf, тобто без https, і
# зʼясується це аж у художника під час першої мережевої дії. А на маку є ще
# гірше: macOS не постачає svn з часів Xcode 11, тож на чистій машині його
# немає ЗОВСІМ, і без цієї теки APSVN там просто не працює.
#
# Техніка та сама, що в make_runtime_mac.sh, тільки ціль менша: скопіювати
# замикання залежностей і переписати абсолютні шляхи на відносні.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SRC_DIR/svn-mac"

SVNBIN="${SVNBIN:-$(command -v svn || true)}"
if [ -z "$SVNBIN" ] || [ ! -x "$SVNBIN" ]; then
  echo "не знайшов svn. Постав його:  brew install subversion" >&2
  echo "або вкажи свій:  SVNBIN=/шлях/до/svn $0" >&2
  exit 1
fi
echo "джерело: $SVNBIN ($("$SVNBIN" --version --quiet))"

rm -rf "$OUT"
mkdir -p "$OUT/bin" "$OUT/lib"

# svnadmin потрібен лише тестам, але лежить поруч і ділить ті самі бібліотеки,
# тож коштує майже нічого — а svn-mac/ від того стає самодостатньою.
for t in svn svnadmin; do
  src="$(dirname "$SVNBIN")/$t"
  [ -x "$src" ] && cp "$src" "$OUT/bin/$t" || echo "  немає $t — пропускаю" >&2
done
chmod u+w "$OUT"/bin/*

python3 - "$OUT" <<'PY'
import os, shutil, subprocess, sys

out = sys.argv[1]
bindir, libdir = os.path.join(out, "bin"), os.path.join(out, "lib")

def deps(path):
    o = subprocess.run(["otool", "-L", path], capture_output=True, text=True)
    return [l.split(" (")[0].strip()
            for l in o.stdout.splitlines()[1:] if l.strip()]

def external(d):
    # /usr/lib і /System є на кожному маку — їх не носять. @-шляхи вже відносні.
    return not (d.startswith("/usr/lib") or d.startswith("/System")
                or d.startswith("@"))

# --- замикання залежностей ---------------------------------------------------
copied, seen = {}, set()
todo = [os.path.join(bindir, f) for f in sorted(os.listdir(bindir))]
while todo:
    p = todo.pop()
    real = os.path.realpath(p)
    if real in seen:
        continue
    seen.add(real)
    for d in deps(p):
        if not external(d):
            continue
        base, src = os.path.basename(d), os.path.realpath(d)
        if base in copied:
            if copied[base] != src:
                sys.exit("СТОП: дві різні бібліотеки звуться однаково: " + base)
            continue
        copied[base] = src
        todo.append(d)

for base, src in sorted(copied.items()):
    shutil.copy2(src, os.path.join(libdir, base))
os.system("chmod u+w '%s'/*.dylib" % libdir)
size = sum(os.path.getsize(os.path.join(libdir, b)) for b in copied)
print("  бібліотек: %d (%.1f МБ)" % (len(copied), size / 1048576))

# --- переносність ------------------------------------------------------------
# Виконувані шукають бібліотеки відносно СЕБЕ (@executable_path), бібліотеки —
# відносно себе ж (@loader_path). Абсолютний шлях у /opt/homebrew на машині
# художника не існує, і svn не запуститься взагалі.
def retarget(path, template, skip_self=False):
    n = 0
    for d in deps(path):
        if not external(d):
            continue
        base = os.path.basename(d)
        if skip_self and base == os.path.basename(path):
            continue
        subprocess.run(["install_name_tool", "-change", d, template % base,
                        path], capture_output=True)
        n += 1
    return n

changed = 0
for f in sorted(os.listdir(bindir)):
    changed += retarget(os.path.join(bindir, f), "@executable_path/../lib/%s")
for f in sorted(os.listdir(libdir)):
    p = os.path.join(libdir, f)
    subprocess.run(["install_name_tool", "-id", "@loader_path/" + f, p],
                   capture_output=True)
    changed += retarget(p, "@loader_path/%s", skip_self=True) + 1
print("  переписано посилань: %d" % changed)

left = []
for d in (bindir, libdir):
    for f in sorted(os.listdir(d)):
        if any(external(x) for x in deps(os.path.join(d, f))):
            left.append(os.path.join(d, f))
if left:
    print("  СТОП: абсолютні посилання лишилися:", *left[:5], sep="\n    ")
    sys.exit(1)
PY

# --- сертифікати -------------------------------------------------------------
# OpenSSL із Homebrew шукає корені в /opt/homebrew/etc/openssl@3/cert.pem —
# теці, якої на машині художника немає, і тоді https не працює взагалі, хоч
# serf і на місці. Своя копія + SSL_CERT_FILE (його виставляє svn_client)
# знімають питання. Це не «про всяк випадок»: без цього кожна дія до сервера
# падає на перевірці сертифіката.
CERT=""
for c in /opt/homebrew/etc/openssl@3/cert.pem /opt/homebrew/etc/ca-certificates/cert.pem \
         /etc/ssl/cert.pem; do
  [ -f "$c" ] && { CERT="$c"; break; }
done
if [ -n "$CERT" ]; then
  cp "$CERT" "$OUT/cert.pem"
  echo "  корені сертифікатів: з $CERT"
else
  echo "  УВАГА: не знайшов cert.pem — https може не працювати" >&2
fi

# --- підпис ------------------------------------------------------------------
# install_name_tool ламає підпис кожного зміненого Mach-O, а на Apple Silicon
# бінарник із побитим підписом не запускається взагалі.
echo "підписую..."
find "$OUT" -type f \( -perm -u+x -o -name "*.dylib" \) -print0 \
  | xargs -0 -n1 codesign --force --sign - 2>/dev/null || true

echo
echo "готово: $OUT  ($(du -sh "$OUT" | cut -f1))"
echo "package_mac.sh підхопить її сам."
