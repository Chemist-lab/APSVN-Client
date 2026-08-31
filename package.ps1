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
$zip = Join-Path (Split-Path $src -Parent) "$name.zip"

New-Item -ItemType Directory -Force -Path $dest | Out-Null
$rc = @($src, $dest, "/E",
        "/XD", "tests", "__pycache__",
        # Збіркове знаряддя не їде до художника — ні наше, ні маківське.
        "/XF", "*.pyc", "package.ps1", "*.sh", "*.apsvn-part",
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
