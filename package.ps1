# Зібрати APSVN для роздачі художникам.
#   powershell -ExecutionPolicy Bypass -File package.ps1
#
# Кладе поруч із текою APSVN файл APSVN.zip. Усередині — сама програма
# з власним Python і svn; встановлювати нічого не треба.
#
# Не потрапляють у пакет:
#   tests/         — наскрізні перевірки, художнику ні до чого;
#   __pycache__/   — кеш Python, він зіпсується при копіюванні на іншу машину;
#   package.ps1    — цей файл.
#
# НЕ входить і не має входити: %APPDATA%\APSVN — там налаштування, паролі
# та швидкості КОНКРЕТНОЇ людини. У кожного вони свої.

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$name = "APSVN"
# Версію беремо з app.py, а не дублюємо тут: два місця розійшлися б на
# першому ж релізі, і кнопка оновлення почала б брехати.
$ver = (Select-String -Path (Join-Path $PSScriptRoot "app.py") `
        -Pattern '^VERSION = "([^"]+)"').Matches[0].Groups[1].Value
"APSVN $ver"
$stage = Join-Path ([IO.Path]::GetTempPath()) ("apsvn_pkg_" + [Guid]::NewGuid().ToString("N"))
$dest = Join-Path $stage $name
# Імʼя з версією, як і в маківської збірки. Без цього на сторінці релізів
# через рік лежать десять файлів APSVN.zip, і завантаживши один, не скажеш,
# яка це версія.
$zip = Join-Path (Split-Path $src -Parent) "$name-$ver.zip"

# Іконку й запускач ПЕРЕЗБИРАЄМО щоразу. Вони лежать у гіті заради
# того, щоб клон був одразу запускним, але це результат збірки. Без цих двох
# рядків достатньо правити make_icon.py і забути його запустити — і в реліз
# мовчки поїде стара іконка.
# Саме СИСТЕМНИЙ python, а не runtime\python.exe. Вбудований рантайм навмисне
# позбавлений pip, а запускач для APSVN.exe береться саме звідти — з
# pip/_vendor/distlib. Під рантаймом збірка падала на «не знайшов w64.exe»,
# і то в кращому разі: перевірка нижче її зупиняє, а не пропускає далі.
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = Join-Path $src "runtime\python.exe" }
& $py (Join-Path $src "make_icon.py") | Out-Null
& $py (Join-Path $src "make_launcher.py") | Out-Null
if (-not (Test-Path (Join-Path $src "APSVN.exe"))) { throw "APSVN.exe не зібрався" }

New-Item -ItemType Directory -Force -Path $dest | Out-Null
$rc = @($src, $dest, "/E",
        "/XD", "tests", "__pycache__",
        # Збіркове знаряддя не їде до художника — ні наше, ні маківське.
        "/XF", "*.pyc", "package.ps1", "*.sh", "*.apsvn-part",
        # Збиральне: малює іконку й зшиває запускач. Готові apsvn.ico,
        # APSVN.exe і ui\icon.png їдуть, а те, чим їх зроблено, — ні.
        "make_icon.py", "make_launcher.py", "peres.py",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
& robocopy @rc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }

if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path $dest -DestinationPath $zip -CompressionLevel Optimal
Remove-Item -LiteralPath $stage -Recurse -Force

"{0}  ({1:N1} MB)" -f $zip, ((Get-Item -LiteralPath $zip).Length / 1MB)

# robocopy повертає 1 на УСПІШНе копіювання, і це число лишається в
# $LASTEXITCODE до самого кінця — без явного exit будь-яка обгортка
# (CI, інший скрипт) читає вдалу збірку як провал.
exit 0
