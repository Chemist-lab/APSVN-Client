# -*- coding: utf-8 -*-
"""Обгортка над svn.exe для APSVN.

Ключові рішення (за результатами аудиту):

* Нічого не-ASCII не потрапляє в argv. svn.exe — не-юнікодна програма: Windows
  конвертує командний рядок у ANSI й підставляє «?» замість непредставних
  символів. Наслідки тихі й важкі: повідомлення «анімація стрибка» назавжди
  лягало б в історію як «????????», а кириличний шлях ставав би «?????» — і
  svn розкривав би його як ШАБЛОН, тобто оперував чужими файлами. Тому шляхи
  йдуть через --targets-файл, повідомлення через -F --encoding UTF-8, а
  робоча копія — через cwd + ціль ".".
* Пароль передається в stdin (--password-from-stdin), а не в argv, де його
  видно у диспетчері задач.
* Приватний --config-dir: auto-props вішає svn:needs-lock на бінарники (без
  цього локи декоративні), global-ignores ховає .blend1 та інший мотлох.
* вікно консолі глушиться через desktop.no_window(): під pythonw кожен
  виклик інакше блимає чорним прямокутником.
* Коди помилок перекладаються людською мовою.
* Застрягла робоча копія (E155004) лікується автоматичним cleanup і повтором.
"""
import ctypes
import datetime
import locale
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

import desktop

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = desktop.svn_candidates(_HERE)


def _find_svn():
    for p in _CANDIDATES:
        if os.path.isfile(p):
            return p
    from shutil import which
    return which("svn") or _CANDIDATES[0]


SVN = _find_svn()

# svnadmin потрібен лише тестам, але шукати його там означало б зашивати
# ".exe" у кожен файл — і жоден із них не запустився б на маку. Ім'я береться
# від самого svn: вони завжди лежать поруч і завжди звуться однаково.
SVNADMIN = os.path.join(os.path.dirname(SVN),
                        "svnadmin.exe" if SVN.lower().endswith(".exe")
                        else "svnadmin")

# Корені сертифікатів для СВОГО svn. OpenSSL, з яким зібраний svn із Homebrew,
# зашитий на /opt/homebrew/etc/openssl@3/cert.pem — теку, якої на машині
# художника немає. Перевірено дослідом, а не припущено: без цього КОЖНА дія до
# https падає з E230001 «issuer is not trusted», хоч serf на місці й https у
# списку схем. Тому make_svn_mac.sh кладе cert.pem поруч зі своїм svn, а тут ми
# лише показуємо, де він.
#
# setdefault, а не присвоєння: якщо адміністратор студії виставив свій
# SSL_CERT_FILE (корпоративний ЦС на проксі — річ цілком реальна), його вибір
# головніший за наш. Через середовище, а не в кожен виклик: підпроцеси
# успадкують самі, і це не розповзається по файлу.
#
# І ЩЕ ОДНЕ, ЩО ЛЕГКО ЗЛАМАТИ ПРИБИРАННЯМ. Від цього рядка залежить не тільки
# svn: той самий OpenSSL стоїть за модулем ssl самого Python, тож саме звідси
# бере корені й updater зі своїм urlopen. Перевірено в зібраному .app —
# Python бачить 192 корені й доходить до GitHub. Якщо колись перенести це
# всередину виклику svn, перевірка оновлень тихо перестане працювати, і
# виглядатиме це як «немає зв'язку», а не як помилка тут.
_CERT = os.path.join(os.path.dirname(os.path.dirname(SVN)), "cert.pem")
if not desktop.WINDOWS and os.path.isfile(_CERT):
    os.environ.setdefault("SSL_CERT_FILE", _CERT)

# файли, які ніколи не потрапляють ані в список, ані в коміт
JUNK_RE = re.compile(
    r"(\.blend\d+$|\.blend@$|\.mine$|\.r\d+$|\.prej$|\.tmp$|~$|"
    r"^Thumbs\.db$|^\.DS_Store$|^desktop\.ini$)", re.I)

# розширення, які не можна зливати -> обовʼязковий лок
# Не «бінарні» в сенсі байтів, а «редагує один за раз»: .ma — узагалі текст,
# але зводити дві правки сцени Maya так само неможливо, як і .blend.
# Unreal тут ОБОВʼЯЗКОВИЙ: без .uasset/.umap локи для UE-проєкту декоративні,
# бо svn:needs-lock ні на що не вішається, файли лишаються перезаписуваними,
# і двоє спокійно правлять один ассет до першого конфлікту.
BINARY_EXT = (".blend", ".abc", ".exr", ".psd", ".psb", ".mov", ".mp4", ".png",
              ".tif", ".tiff", ".jpg", ".jpeg", ".tga", ".dds", ".hdr",
              ".fbx", ".obj", ".usd", ".usdc", ".usdz", ".vdb", ".wav",
              ".mkv", ".zip",
              # Unreal Engine
              ".uasset", ".umap", ".uexp", ".ubulk",
              # Maya, 3ds Max, Cinema 4D, Houdini, Nuke, Substance, ZBrush
              ".ma", ".mb", ".max", ".c4d", ".3ds",
              ".hip", ".hipnc", ".hiplc", ".nk", ".nknc",
              ".spp", ".sbs", ".sbsar", ".ztl", ".zpr")

CONFIG_BODY = """### Created by APSVN — do not edit by hand.
[auth]
store-passwords = yes
store-auth-creds = yes
password-stores = windows-cryptoapi

[miscellany]
enable-auto-props = yes
global-ignores = *.blend1 *.blend2 *.blend[0-9]* *.blend@ *.mine *.r[0-9]* *.prej *.tmp *~ Thumbs.db .DS_Store desktop.ini

[auto-props]
""" + "\n".join("*%s = svn:needs-lock=*" % e for e in BINARY_EXT) + "\n"

# Види конфлікту та як вони звучать у списку. Слово CONFLICT лишається
# першим у кожному рядку — за ним художник упізнає біду, не читаючи решти.
CONFLICT_TEXT = {
    "text": "CONFLICT",
    "tree": "CONFLICT · moved or deleted",
    "prop": "CONFLICT · file settings",
    "obstructed": "CONFLICT · your file is in the way",
}

STATUS_TEXT = {
    "modified": "changed", "added": "added", "deleted": "deleted",
    "unversioned": "new", "missing": "gone from your folder",
    "conflicted": "CONFLICT", "replaced": "replaced", "normal": "",
    "none": "", "ignored": "ignored", "obstructed": "blocked",
}

# Рядок, за яким app.py і тести впізнають успішний коміт. Окремою сталою, бо
# інакше вони чіплялися б за сам текст повідомлення — і будь-яке його
# переформулювання тихо ламало б і підказку про локи, і прибирання видалених.
COMMIT_RE = re.compile(r"\bcommit (\d+)\b")


class SvnError(Exception):
    """Помилка svn з уже людським текстом (оригінал — у .raw)."""

    def __init__(self, human, raw=""):
        super().__init__(human)
        self.raw = raw or human


# --- кодування -------------------------------------------------------------
def _acp():
    """Кодова сторінка, у якій svn.exe читає argv.

    Поза Windows питання не стоїть узагалі: argv там у UTF-8, і вся драбина
    кодувань нижче вироджується в перший же крок.
    """
    if not desktop.WINDOWS:
        return "utf-8"
    try:
        return "cp%d" % ctypes.windll.kernel32.GetACP()
    except Exception:
        return locale.getpreferredencoding(False) or "cp1252"


def _dec(b):
    """svn пише повідомлення в кодуванні консолі, а не в UTF-8."""
    if isinstance(b, str):
        return b
    for enc in ("utf-8", _acp(), "cp1251", "mbcs"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return b.decode("mbcs", "replace")


def _short(path):
    """8.3-псевдонім — ASCII-шлях там, де оригінал кириличний.

    Суто віконна річ: 8.3-імена існують лише на файлових системах Microsoft, і
    потрібні лише тому, що svn.exe не юнікодний. Деінде повертаємо None, і
    виклик іде далі звичайним шляхом.
    """
    if not desktop.WINDOWS:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024)
        return buf.value if n else None
    except Exception:
        return None


def _ascii_path(path):
    """Шлях, який гарантовано переживе ANSI-argv, або None."""
    cp = _acp()
    for cand in (path, _short(path)):
        if not cand:
            continue
        try:
            cand.encode(cp)
            return cand
        except UnicodeEncodeError:
            continue
    return None


# --- людські повідомлення --------------------------------------------------
_HUMAN = [
    # Порядок має значення: перше правило, яке збіглося, і перемагає.
    (r"E155004|E155037|E155009",
     "The project is busy with an unfinished action. Click “Repair”."),
    # W160042 мусить стояти ПЕРЕД загальним правилом про локи: це не «зайнято
    # колегою», а «твоя копія відстала». Порада тут протилежна.
    (r"W160042|newer version of",
     "Your folder is out of date. Click “Get latest” first."),
    (r"W160035|E160039|E195022|E160037|423 Locked",
     "Somebody else has this file locked — ask them to submit their work "
     "and release it."),
    (r"E155011|E160028|E170004",
     "Somebody has already submitted a newer version. Click “Get latest” first."),
    (r"E155015|E155027", "This file has a conflict — choose whose version to keep."),
    (r"E155035", "This file has a conflict — choose whose version to keep first."),
    (r"E195013", "You do not hold this file any more — there is nothing to release."),
    (r"E170001|E215004|Authorization failed", "That user name or password is not right."),
    (r"E170013|E731001|Unable to connect|Could not resolve",
     "No connection to the server. Check your internet and try again."),
    (r"E170011", "This project has moved to a new address."),
    (r"E155000", "This folder already holds a different project."),
    # «не під версійним контролем» — окремо від «теку теж треба здати»:
    # порада тут інша, і сира англійська фраза сюди просочувалась
    (r"is not under version control",
     "This file is not in the project yet. Submit it first — the Files tab "
     "shows everything that is new."),
    (r"E200009.*not known to exist|is not part of the commit",
     "You have to submit the folder the files are in as well. "
     "Tick the folder too."),
    (r"E150002", "A file with that name already exists — click “Get latest” first."),
    # E195012/E160013 — саме про ОДИН файл у старій ревізії, а не про проєкт
    (r"E195012|E160013",
     "This file did not exist yet in that version — pick another date."),
    (r"E155007|E155036",
     "This folder is not a project folder — connect to the project again."),
    # E155010 віддає і звичайний propset на кириличному шляху, тож радити
    # «переприєднай проєкт» тут не можна — це збиває людину з пантелику
    (r"E155010", "svn could not find this file in the project."),
    (r"E200030|E200033|database disk image",
     "The project’s internal database is damaged. Click “Repair”."),
    (r"E205005", "Your note was not accepted — try different wording."),
    (r"E720123|E720003", "Something is wrong with the path or with your access rights."),
    (r"E170000|404 Not Found", "The server could not find that project."),
]


def humanize(raw):
    for pat, msg in _HUMAN:
        if re.search(pat, raw, re.I):
            return msg
    first = [l for l in raw.splitlines() if l.strip()]
    return first[-1] if first else "Something went wrong (svn)"


# --- запуск ----------------------------------------------------------------
_config_dir = None


def _write_atomic(path, body):
    """Запис через tmp + replace.

    Прямий open(...,'w') лишає файл порожнім на мить. Якщо саме в цю мить
    svn прочитає config, файл, доданий тоді ж, назавжди лишиться без
    svn:needs-lock — лок для нього стане декоративним, і помітити це нічим.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(0.15)   # svn може саме тримати файл відкритим
    os.replace(tmp, path)


def ensure_config(appdata_dir):
    """Приватний config-dir з auto-props і global-ignores."""
    global _config_dir
    d = os.path.join(appdata_dir, "svnconfig")
    os.makedirs(d, exist_ok=True)
    cfg = os.path.join(d, "config")
    try:
        same = open(cfg, encoding="utf-8").read() == CONFIG_BODY
    except Exception:
        same = False
    if not same:
        _write_atomic(cfg, CONFIG_BODY)
    srv = os.path.join(d, "servers")
    if not os.path.exists(srv):
        _write_atomic(srv, "[global]\nstore-passwords = yes\n")
    _config_dir = _ascii_path(d) or d
    return _config_dir


_stdin_pw = None


def supports_stdin_password():
    """Чи вміє ЦЕЙ svn читати пароль зі stdin.

    Не риторичне питання: SlikSvn 1.14.2 опцію --password-from-stdin приймає
    мовчки, але пароль не читає — і кожна мережева дія падає з «Authentication
    failed». Тести на file://-репозиторії цього не бачать, бо там автентифікації
    немає взагалі. Тому питаємо сам svn один раз локально, без мережі.

    "-v" додається ЛИШЕ ПОЗА WINDOWS, і це не косметика. svn 1.14.5 з Homebrew
    ховає глобальні опції з "svn help <підкоманда>": там немає навіть рядка про
    --password, лише підказка «Use -v to show global and experimental options».
    Тобто проба казала «не вміє» про збірку, яка вміє — перевірено дослідом на
    справжньому svnserve з паролем: правильний пароль зі stdin пускає,
    неправильний відхиляється (tests/exp_stdin_password.py). Наслідок був тихий
    і неприємний: на маку APSVN ішов запасним шляхом і клав пароль у argv, де
    його видно в списку процесів.

    Віконну гілку проби не чіпаємо навмисно. Саме її результат (False) уводить
    SlikSvn на запасний шлях, а SlikSvn прапорець приймає й ігнорує — тож
    помилитися тут означає покласти кожну мережеву дію в художника. Перевірити
    наслідки такої зміни з мака неможливо, отже й змінювати нічого.
    """
    global _stdin_pw
    if _stdin_pw is None:
        cmd = [SVN, "help", "status"] + ([] if desktop.WINDOWS else ["-v"])
        try:
            r = subprocess.run(cmd, capture_output=True,
                               **desktop.no_window(),
                               stdin=subprocess.DEVNULL, timeout=30)
            _stdin_pw = "--password-from-stdin" in _dec(r.stdout)
        except Exception:
            _stdin_pw = False
    return _stdin_pw


def _fits(text, enc):
    try:
        text.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _targets_file(paths, cwd=None):
    """Шляхи — окремим файлом, бо в argv не-ASCII перетворюється на «?».

    Кодування добираємо сходинками (перевірено дослідом на ACP=cp1252):
      1. ACP — рідне для svn, працює завжди, коли шлях у ньому представний;
      2. 8.3-псевдонім для непредставних імен — чистий ASCII, найнадійніше;
      3. кирилична cp1251 (чи інша ANSI) для решти — зокрема для файлів,
         яких уже немає на диску, бо для них 8.3 не існує.
    UTF-8 і UTF-16 svn у --targets не приймає — не пропонувати.
    """
    cp = _acp()
    lines = list(paths)
    enc = cp

    if not all(_fits(p, cp) for p in lines):
        subst, ok = [], True
        for p in lines:
            if _fits(p, cp):
                subst.append(p)
                continue
            full = p if os.path.isabs(p) else os.path.join(cwd or ".", p)
            sp = _short(full)
            if sp and _fits(sp, cp):
                subst.append(sp)
            else:
                ok = False
                break
        if ok:
            lines = subst
        else:
            for alt in ("cp1251", "cp1250", "cp1254", "cp1253"):
                if all(_fits(p, alt) for p in lines):
                    enc = alt
                    break
            else:
                raise SvnError(
                    "“%s” has characters that svn on this computer "
                    "cannot handle. Rename it using Latin letters." % lines[0])

    # Вміст --targets проходить той самий розбір peg-ревізії, що й argv:
    # рядок 'shot@010.blend' дає «a peg revision is not allowed here», і через
    # це ЛАМАЛИСЬ усі операції над таким файлом — commit, lock, add, delete,
    # revert. Хвостова '@' знімає розбір. Імена на кшталт 'render@2x.png' у
    # художників цілком реальні.
    lines = [l + "@" for l in lines]

    fd, name = tempfile.mkstemp(prefix="apsvn_t", suffix=".txt")
    os.close(fd)
    safe = _ascii_path(name)
    if safe is None:
        os.unlink(name)
        raise SvnError("The temp folder path has unusual characters — move "
                       "the project to a folder with a Latin name.")
    with open(safe, "w", encoding=enc, newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return safe


def _message_file(text):
    fd, name = tempfile.mkstemp(prefix="apsvn_m", suffix=".txt")
    os.close(fd)
    safe = _ascii_path(name)
    if safe is None:
        os.unlink(name)
        return None
    with open(safe, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return safe


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong)]


def _io_read(handle):
    """Скільки байтів процес svn.exe уже прочитав.

    Це НЕ відсоток переданого: залежно від транспорту svn перечитує файли
    2.0-2.9 разу (перевірено дослідом), тож ділити на обсяг не можна. А от
    ПОХІДНА цієї величини — справжня, виміряна швидкість роботи, і саме її
    варто показати замість тиші.
    """
    if not desktop.WINDOWS:
        # На маку прямого аналога немає (psutil там io_counters не вміє), тож
        # виміряної швидкості просто не буде — лишиться оцінка за історією.
        return None
    try:
        c = _IO_COUNTERS()
        if ctypes.windll.kernel32.GetProcessIoCounters(int(handle),
                                                       ctypes.byref(c)):
            return c.ReadTransferCount
    except Exception:
        pass
    return None


# Рядки, які svn лишає незавершеними, поки триває довга робота.
_PARTIAL_MARKERS = ("Transmitting file data", "Committing transaction")


def _stream_lines(cmd, cwd, stdin_data, on_line, on_io=None):
    """Читати stdout ЖИВЦЕМ, віддаючи рядки по ходу.

    Перевірено дослідом: svn.exe не буферизує вивід у трубу — на коміті 305
    рядків прийшли рівномірно за 9.9 с. Тому за цими рядками можна показувати
    чесний поступ «файл N з M».

    Читаємо через os.read: він повертає те, що вже прийшло, а не чекає повного
    буфера — інакше вся жвавість втрачається.
    """
    p = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if stdin_data else subprocess.DEVNULL,
        **desktop.no_window(), bufsize=0)
    if stdin_data:
        try:
            p.stdin.write(stdin_data)
            p.stdin.flush()
        except OSError:
            pass
        try:
            p.stdin.close()
        except OSError:
            pass

    err = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    t.start()

    if on_io is not None:
        def sample():
            while p.poll() is None:
                n = _io_read(p._handle)
                if n is not None:
                    try:
                        on_io(n)
                    except Exception:
                        pass
                time.sleep(0.5)
        threading.Thread(target=sample, daemon=True).start()

    out = bytearray()
    buf = bytearray()
    seen_marker = None
    fd = p.stdout.fileno()
    while True:
        try:
            chunk = os.read(fd, 8192)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        buf += chunk
        parts = re.split(rb"[\r\n]", bytes(buf))
        buf = bytearray(parts.pop())

        # «Transmitting file data ....» svn друкує БЕЗ переводу рядка: крапки
        # доростають поступово, а рядок закривається аж коли передача скінчилась.
        # Якщо чекати на кінець рядка, перехід у фазу передачі приходить уже
        # ПІСЛЯ неї — і смуга висить на 100% з іменем останнього переліченого
        # файлу, хоч саме тоді й іде найдовша частина роботи.
        pending = _dec(bytes(buf)).lstrip()
        for marker in _PARTIAL_MARKERS:
            if pending.startswith(marker) and marker != seen_marker:
                seen_marker = marker
                try:
                    on_line(marker)
                except Exception:
                    pass
                break

        for raw in parts:
            line = _dec(bytes(raw)).strip()
            if line:
                try:
                    on_line(line)
                except Exception:
                    pass          # поступ ніколи не має валити саму операцію
    tail = _dec(bytes(buf)).strip()
    if tail:
        try:
            on_line(tail)
        except Exception:
            pass
    p.wait()
    t.join(timeout=5)
    return p.returncode, bytes(out), (err[0] if err else b"")


def _stream(cmd, cwd, stdin_data, dest):
    """Вилити stdout процесу просто у файл, не тримаючи його в памʼяті."""
    try:
        with open(dest, "wb") as fh:
            p = subprocess.Popen(
                cmd, cwd=cwd, stdout=fh, stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if stdin_data else subprocess.DEVNULL,
                **desktop.no_window())
            _, err = p.communicate(input=stdin_data)
        return p.returncode, b"", err
    except OSError as e:
        raise SvnError("Could not write the file: %s" % (e.strerror or e))


def _run(args, cwd=None, username=None, password=None, timeout=120,
         targets=None, message=None, _retry=True, stdout_to=None,
         notifier=None):
    """Єдина точка виклику svn.exe.

    stdout_to — шлях, у який лити stdout потоком замість буферизації. Потрібен
    для `svn cat`: .blend на кілька гігабайтів у capture_output осів би в
    памʼяті цілком (та ще й з копією при .stdout).
    notifier — обʼєкт _Notifier: .line() дістає рядки виводу, .io() — лічильники
    вводу-виводу процесу.
    """
    if not os.path.isfile(SVN):
        # Текст різний, бо причини різні. На Windows svn їде в комплекті, тож
        # його відсутність означає рівно одне: теку скопіювали не всю. На маку
        # збірка поки що позичає системний svn, а macOS свого не має з часів
        # Xcode 11 — тобто найімовірніше його просто ніде взяти. Порада «візьми
        # теку цілком» там не веде нікуди, а «svn.exe» на маку не існує взагалі.
        raise SvnError(
            "svn.exe is missing. It looks like APSVN was copied "
            "only partly — you need the whole folder, including "
            "the svn subfolder."
            if desktop.WINDOWS else
            "Subversion is missing. APSVN needs the “svn” command line tool, "
            "and macOS does not ship one. Install it with:\n\n"
            "    brew install subversion")
    cmd = [SVN] + list(args)
    if _config_dir:
        cmd += ["--config-dir", _config_dir]
    cmd += ["--non-interactive"]

    tmp = []
    try:
        if targets:
            tf = _targets_file(targets, cwd)
            tmp.append(tf)
            cmd += ["--targets", tf]
        if message is not None:
            mf = _message_file(message)
            if mf:
                tmp.append(mf)
                cmd += ["-F", mf, "--encoding", "UTF-8", "--force-log"]
            else:
                cmd += ["-m", message, "--force-log"]

        stdin_data = None
        if username:
            cmd += ["--username", username]
        if password:
            if supports_stdin_password():
                cmd += ["--password-from-stdin"]
                stdin_data = (password + "\n").encode("utf-8")
            else:
                # Запасний шлях для збірок без підтримки stdin. Пароль тут
                # видно в списку процесів, тому дозволяємо svn закешувати його
                # у власному --config-dir: на Windows кеш шифрується DPAPI під
                # цього користувача, і наступні виклики пароля вже не несуть.
                cmd += ["--password", password]

        if stdout_to is not None:
            rc, out, err = _stream(cmd, cwd, stdin_data, stdout_to)
        elif notifier is not None:
            rc, out, err = _stream_lines(cmd, cwd, stdin_data,
                                         notifier.line, notifier.io)
        else:
            kw = dict(cwd=cwd, capture_output=True, timeout=timeout,
                      **desktop.no_window())
            if stdin_data is None:
                kw["stdin"] = subprocess.DEVNULL
            else:
                kw["input"] = stdin_data
            try:
                r = subprocess.run(cmd, **kw)
            except subprocess.TimeoutExpired:
                raise SvnError("This took too long and was stopped. Click "
                               "again — nothing you already downloaded "
                               "is lost.")
            except OSError as e:
                raise SvnError("Could not start svn: %s" % (e.strerror or e))
            rc, out, err = r.returncode, r.stdout, r.stderr

        if rc != 0:
            raw = _dec(err).strip() or _dec(out).strip()
            # E155037/E155009 — «попередня операція не завершилась»: без них
            # одна невдала спроба відновлення файлу виводила з ладу ВЕСЬ
            # проєкт, доки людина сама не натисне «Полагодити»
            if _retry and cwd and re.search(
                    r"E155004|E200033|E155037|E155009|run.*cleanup", raw, re.I):
                try:
                    _run(["cleanup", "."], cwd=cwd, timeout=None, _retry=False)
                except SvnError:
                    pass
                return _run(args, cwd=cwd, username=username, password=password,
                            timeout=timeout, targets=targets, message=message,
                            _retry=False, stdout_to=stdout_to,
                            notifier=notifier)
            raise SvnError(humanize(raw), raw)
        return out
    finally:
        for f in tmp:
            try:
                os.unlink(f)
            except OSError:
                pass


def _xml(args, **kw):
    return ET.fromstring(_run(args + ["--xml"], **kw))


def _rel(p):
    p = (p or "").replace("\\", "/")
    return p[2:] if p.startswith("./") else p


# --- операції --------------------------------------------------------------
def info(wc):
    root = _xml(["info", "."], cwd=wc, timeout=60)
    e = root.find("entry")
    return {"url": e.findtext("url"), "revision": e.get("revision"),
            "root": e.findtext("repository/root")}


LIST_CAP = 2000            # скільки файлів показувати в розгорнутій теці
COUNT_CAP = 20000          # доки рахувати вміст, щоб не вішати опитування


def _scan_new(wc, rel, cap, want_names):
    """Обійти НЕверсіоновану теку через scandir.

    `svn status` навмисно не заходить усередину такої теки — віддає один рядок
    на всю теку. Художник, який перетягнув теку з кадрами, бачив би самий лише
    її рядок і не міг би ані переглянути вміст, ані вибрати окремі файли.

    scandir, а не os.walk: розмір файлу приходить разом із записом теки, без
    окремого stat на кожен файл.
    """
    root = os.path.join(wc, rel.replace("/", os.sep))
    names, n, total, cut = [], 0, 0, False
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in sorted(entries, key=lambda x: x.name.lower()):
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name != ".svn":
                        stack.append(e.path)
                    continue
                if JUNK_RE.search(e.name):
                    continue
                n += 1
                try:
                    total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
                if want_names:
                    names.append(os.path.relpath(e.path, wc).replace("\\", "/"))
                if n >= cap:
                    cut = True
                    stack = []
                    break
            except OSError:
                continue
    return names, n, total, cut


def dir_summary(wc, rel):
    """Скільки всього у кинутій теці — для рядка списку."""
    _, n, total, cut = _scan_new(wc, rel, COUNT_CAP, False)
    return {"n_files": n, "bytes": total, "counted_all": not cut}


def list_new(wc, rel, cap=LIST_CAP):
    """Файли всередині кинутої теки — на запит, коли її розгорнули."""
    names, n, total, cut = _scan_new(wc, rel, cap, True)
    return {"files": [{"path": p, "binary": p.lower().endswith(BINARY_EXT)}
                      for p in sorted(names, key=str.lower)],
            "truncated": cut}


def status(wc, remote=False, username=None, password=None, me=None, meta=None):
    """Список того, що змінилося. У meta (якщо дали) кладемо ревізію сервера."""
    args = ["status", "."]
    if remote:
        args.insert(1, "-u")
    root = _xml(args, cwd=wc, timeout=None if remote else 120,
                username=username if remote else None,
                password=password if remote else None)
    if meta is not None:
        ag = root.find("target/against")
        meta["head"] = ag.get("revision") if ag is not None else None
    items = []
    for tgt in root.findall("target"):
        for e in tgt.findall("entry"):
            path = _rel(e.get("path"))
            if not path or JUNK_RE.search(os.path.basename(path)):
                continue
            # вкладена робоча копія: інакше вона показується рядком «нове»,
            # галочку поставити можна, а здача падає сирою англійською —
            # svn add на корінь чужої копії не працює
            if os.path.isdir(os.path.join(wc, path.replace("/", os.sep), ".svn")):
                continue
            ws, rs = e.find("wc-status"), e.find("repos-status")
            st = ws.get("item") if ws is not None else "none"
            if st == "ignored":
                continue

            # ЧОМУ НЕ ЛИШЕ item. svn тримає деревʼяний конфлікт і конфлікт
            # властивостей в ОКРЕМИХ атрибутах, а в item тим часом стоїть
            # цілком мирне значення. Перевірено дослідом на живому репозиторії
            # (tests/test_conflicts.py повторює його крок у крок):
            #   колега видалив файл, я його правив ->
            #       item="added" copied="true" tree-conflicted="true"
            #   мій файл лежить на місці того, що приїхав ->
            #       item="deleted" tree-conflicted="true"  (файл НА ДИСКУ!)
            #   зачеплено властивість з обох боків ->
            #       item="normal" props="conflicted"
            # Читаючи саме item, ми показували художникові мирний зелений
            # рядок «added» — він ставив галочку, тиснув Submit і отримував
            # відмову, а кнопки, щоб її виправити, у нього не було взагалі.
            # Тепер будь-який конфлікт стає status "conflicted", і всі наявні
            # запобіжники (заборона коміту, група «Needs your decision»,
            # червоний рядок, сортування вгору) вмикаються самі собою.
            tree_conf = ws is not None and ws.get("tree-conflicted") == "true"
            prop_conf = ws is not None and ws.get("props") == "conflicted"
            kind = None
            if st == "conflicted":
                kind = "text"
            elif tree_conf:
                # Перешкода відрізняється від решти деревʼяних конфліктів тим,
                # що файл ФІЗИЧНО лежить на диску — і це файл художника. Без
                # цієї гілки APSVN підписував його «deleted», тобто прямо
                # брехав про власну незбережену роботу людини.
                on_disk = os.path.isfile(
                    os.path.join(wc, path.replace("/", os.sep)))
                kind = "obstructed" if (st == "deleted" and on_disk) else "tree"
            elif prop_conf:
                kind = "prop"
            wl = ws.find("lock") if ws is not None else None
            rl = rs.find("lock") if rs is not None else None
            # Коли ми питали сервер — головує ВІН. Відсутність rl тоді означає,
            # що лока більше немає (зняли адміністративно чи вкрали), а не що
            # ми просто не знаємо. Без цієї різниці людина цілий день малює
            # «під локом», якого не існує, і втрачає роботу на коміті.
            if remote:
                owner = rl.findtext("owner") if rl is not None else None
                same = (rl is not None and wl is not None and
                        rl.findtext("token") == wl.findtext("token"))
                mine = bool(same and (me is None or owner == me))
                stale = bool(wl is not None and not mine)
            else:
                owner = wl.findtext("owner") if wl is not None else None
                mine = bool(wl is not None and (me is None or owner == me))
                stale = False
            remote_change = rs is not None and rs.get("item") not in (None, "none")
            remote_kind = rs.get("item") if remote_change else None
            if st in ("normal", "none") and not remote_change \
                    and not owner and not stale and not kind:
                continue
            items.append({
                "path": path,
                "status": "conflicted" if kind else st,
                "wc_item": st,                    # що насправді сказав svn
                "conflict_kind": kind,            # text | tree | prop | obstructed
                "status_text": (CONFLICT_TEXT[kind] if kind
                                else STATUS_TEXT.get(st, st)),
                "remote_change": remote_change, "remote_kind": remote_kind,
                "lock_owner": owner,
                "lock_mine": mine, "lock_stale": stale,
                "binary": path.lower().endswith(BINARY_EXT),
            })
    # Кинуту теку лишаємо одним рядком, але з лічильником вмісту — щоб було
    # видно, що всередині щось є, і щоб її можна було розгорнути на вимогу.
    # Вивалювати тисячі рядків одразу не можна: у такому списку нічого не
    # знайти, а перемальовується він щоразу при опитуванні.
    for it in items:
        if it["status"] == "unversioned" and                 os.path.isdir(os.path.join(wc, it["path"].replace("/", os.sep))):
            it["dir"] = True
            it.update(dir_summary(wc, it["path"]))
    items.sort(key=lambda x: (not x["lock_stale"], x["status"] != "conflicted",
                              x["path"].lower()))
    return items


def _revision_of(out):
    m = re.findall(r"revision (\d+)", out)
    return m[-1] if m else None


def update(wc, username=None, password=None, progress=None, total=None):
    out = _dec(_run(["update", ".", "--accept", "postpone"], cwd=wc,
                    username=username, password=password, timeout=None,
                    notifier=_notifier(progress, "download", total, wc) if progress else None))
    # svn говорить англійською навіть в українській Windows — переказуємо самі
    conflicts = sum(1 for l in out.splitlines()
                    if l[:1] == "C" and l[1:2] in " CU")
    m = re.search(r"(?:Text|Tree|Property) conflicts:\s*(\d+)", out)
    if m:
        conflicts = max(conflicts, int(m.group(1)))
    changed = sum(1 for l in out.splitlines() if l[:1] in "AUDGE" and l[1:2] in " CU")
    rev = _revision_of(out)
    head = ("Up to date with commit %s" % rev) if rev else "Up to date"
    if changed:
        head += " — files updated: %d" % changed
    elif not conflicts:
        head += " — everything was already up to date"
    if conflicts:
        head += (". WARNING: %d conflict(s). Choose whose version to keep."
                 % conflicts)
    return head


def commit(wc, paths, message, username=None, password=None, progress=None,
           total=None, total_bytes=None, rate_hint=None, keep_locks=True):
    if not paths:
        raise SvnError("No files selected")
    # --no-unlock: svn за замовчуванням знімає лок на коміті, і файл з
    # svn:needs-lock тієї ж миті стає read-only. Художник з відкритим Blender
    # здає проміжну версію, працює далі, тисне Ctrl+S — і отримує відмову
    # запису на роботу, якої ще немає в репозиторії. Лок тримаємо, поки його
    # не відпустять кнопкою.
    args = ["commit"] + (["--no-unlock"] if keep_locks else [])
    out = _dec(_run(args, cwd=wc, targets=paths,
                    message=message, username=username, password=password,
                    timeout=None,
                    notifier=_notifier(progress, "upload", total or len(paths),
                                       wc, total_bytes, rate_hint)
                    if progress else None))
    m = re.search(r"Committed revision (\d+)", out)   # svn.exe завжди англійський
    if m:
        return "Sent. This is commit %s — your team can see your work now." % m.group(1)
    return "Nothing was sent — everything was already up to date"


def add(wc, paths):
    _run(["add", "--parents"], cwd=wc, targets=paths, timeout=None)


def remove(wc, paths):
    """Позначити файли на видалення — не прибираючи їх з диска одразу.

    Звичайний `svn delete` стирає файл із диска, а разом із ним зникає його
    8.3-псевдонім. Для імені, якого немає в жодному ANSI-кодуванні (наприклад
    з українським апострофом «ʼ», U+02BC), після цього не лишається способу
    назвати файл у наступному коміті — і видалення неможливо здати взагалі.
    Тому --keep-local, а з диска приберемо самі, коли коміт пройде.

    Якщо файл уже стерли в Провіднику, підкладаємо порожній файл-заглушку:
    Windows видає 8.3-псевдонім лише тому, що існує. Перевірено дослідом,
    tests/exp_delete.py.
    """
    cp = _acp()
    for p in paths:
        full = os.path.join(wc, p.replace("/", os.sep))
        if not os.path.exists(full) and not _fits(p, cp):
            try:
                open(full, "w").close()
            except OSError:
                pass
    _run(["delete", "--keep-local", "--force"], cwd=wc, targets=paths, timeout=300)


def purge_deleted(wc, paths):
    """Прибрати з диска те, що вже видалено в репозиторії (після коміту)."""
    for p in paths:
        full = os.path.join(wc, p.replace("/", os.sep))
        try:
            if os.path.isfile(full):
                os.chmod(full, 0o666)   # svn:needs-lock лишає файли read-only
                os.unlink(full)
        except OSError:
            pass


def revert(wc, paths):
    _run(["revert", "--depth", "infinity"], cwd=wc, targets=paths, timeout=600)


def resolve(wc, paths, choice="mine-full"):
    _run(["resolve", "--accept", choice], cwd=wc, targets=paths, timeout=600)


def resolve_conflict(wc, path, kind, choice="mine"):
    """Вивести файл із конфлікту. choice: mine | theirs | working.

    ЯКА КОМАНДА ЩО РОБИТЬ — встановлено дослідом, не з документації, бо
    документація тут вводить в оману. Дослід повторюється в
    tests/test_conflicts.py; підсумок:

      текстовий і бінарний  --accept mine-full / theirs-full  працюють;
      ДЕРЕВʼЯНИЙ і ПЕРЕШКОДА  mine-full і theirs-full НЕ ВИРІШУЮТЬ НІЧОГО —
          svn мовчки лишає файл у конфлікті, людина думає, що впоралась, і
          натикається на ту саму відмову при наступній здачі. Працюють лише
          `--accept working` (лишити своє) і `revert` (взяти командне);
      властивості  працює будь-що.

    `working` окремим варіантом — для того, хто відкрив файл, звів обидві
    правки руками й хоче лишити саме ЗВЕДЕНЕ. Без нього «keep my version»
    підставляла .mine і тихо викидала ручну роботу: перевірено, у файлі
    після цього лишався доконфліктний текст.
    """
    if choice == "working":
        _run(["resolve", "--accept", "working"], cwd=wc, targets=[path],
             timeout=600)
        return
    if kind in ("tree", "obstructed"):
        if choice == "mine":
            _run(["resolve", "--accept", "working"], cwd=wc, targets=[path],
                 timeout=600)
        else:
            revert(wc, [path])
        return
    resolve(wc, [path], "mine-full" if choice == "mine" else "theirs-full")


def rescue_copy(wc, path, rescue_dir):
    """Копія нинішніх байтів у теку порятунку. None — копіювати не було чого.

    Потрібна перед КОЖНОЮ дією, що затирає файл. svn прибирає .mine тим самим
    викликом, яким вирішує конфлікт, тож без цієї копії «взяти версію колеги»
    знищувала день роботи безповоротно.
    """
    full = os.path.join(wc, path.replace("/", os.sep))
    if not rescue_dir or not os.path.isfile(full):
        return None
    try:
        os.makedirs(rescue_dir, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        saved = os.path.join(rescue_dir,
                             "%s %s" % (stamp, os.path.basename(path)))
        with open(full, "rb") as src, open(saved, "wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
        return saved
    except OSError:
        return None


_ALREADY = re.compile(r"already locked by user '([^']*)'", re.I)


def lock(wc, paths, username=None, password=None, me=None):
    """Зайняти файли.

    Лок на файл, який ти ВЖЕ тримаєш, svn віддає як помилку W160035 «already
    locked by user 'X'». Загальне правило humanize() перекладає це як «зайнято
    іншою людиною» — і найзвичайніший шлях (художник тримає лок, бо саме тому
    й редагує файл) впирався б у пораду піти спитати неіснуючого колегу.
    Тому: якщо X — це ми, вважаємо успіхом.
    """
    try:
        return _dec(_run(["lock"], cwd=wc, targets=paths, message="APSVN",
                         username=username, password=password,
                         timeout=300)).strip()
    except SvnError as e:
        m = _ALREADY.search(e.raw or "")
        who = m.group(1) if m else None
        if not (who and me and who == me):
            raise
        # «зайнято тобою» ще не означає «зайнято ЦІЄЮ копією»: лок може висіти
        # з іншого компʼютера. Тоді токена тут немає, запис на диск пройде, а
        # коміт упаде з E160037 — рівно та катастрофа, якої ми уникаємо.
        if all(holds_lock(wc, p) for p in paths):
            return "You already have this file locked"
        raise SvnError(
            "You have this file locked somewhere else — on another computer, "
            "or in another copy of this project. Release it there and try again.",
            e.raw)


def holds_lock(wc, path):
    """Чи тримає ЦЯ робоча копія токен лока на файл.

    Через повний status(), бо `svn status` — ще одна підкоманда, яка НЕ
    приймає --targets (як cat, copy, list і propget). Без -u це локальна
    операція, тож обійти копію дешево.
    """
    try:
        # me=None -> «мій» означає саме «токен є в цій копії»
        return any(i["path"] == path and i["lock_mine"] for i in status(wc))
    except SvnError:
        return False


def unlock(wc, paths, username=None, password=None):
    return _dec(_run(["unlock"], cwd=wc, targets=paths,
                     username=username, password=password, timeout=300)).strip()


def files_under(wc, rel, remote=False, username=None, password=None):
    """Версіоновані ФАЙЛИ всередині теки — те, що взагалі можна зайняти.

    Теки сюди не потрапляють навмисно: Subversion лок на теку не видає
    (перевірено дослідом), тож «зайняти теку» може означати лише «зайняти
    все, що в ній».
    """
    full = os.path.join(wc, (rel or "").replace("/", os.sep))
    args = ["status", ".", "-v"]
    if remote:
        args.insert(2, "-u")
    root = _xml(args, cwd=full, timeout=None if remote else 300,
                username=username if remote else None,
                password=password if remote else None)
    out = []
    for tgt in root.findall("target"):
        for e in tgt.findall("entry"):
            p = _rel(e.get("path") or "").replace("\\", "/")
            if not p or p == ".":
                continue
            ws = e.find("wc-status")
            if ws is None or ws.get("item") in ("unversioned", "ignored",
                                                "none", "external"):
                continue
            if JUNK_RE.search(os.path.basename(p)):
                continue
            if not os.path.isfile(os.path.join(full, p.replace("/", os.sep))):
                continue                      # теки й зниклі файли не локаємо
            wl = ws.find("lock")
            rs = e.find("repos-status")
            rl = rs.find("lock") if rs is not None else None
            out.append({
                "path": ((rel + "/") if rel else "") + p,
                "mine": wl is not None,
                "other": (rl.findtext("owner")
                          if (rl is not None and wl is None) else None),
            })
    return out


def lock_folder(wc, rel, me=None, username=None, password=None, progress=None):
    """Зайняти все, що в теці.

    svn повертає помилку на ВСЮ операцію, якщо хоч один файл тримає колега,
    але решту при цьому все одно займає (перевірено: 118 зі 120). Тому
    результат рахуємо не з коду завершення, а зі свіжого status — інакше
    людині сказали б «не вийшло», хоч насправді вона взяла сотню локів.
    """
    items = files_under(wc, rel, remote=True, username=username,
                        password=password)
    if not items:
        raise SvnError("There is nothing to lock in this folder.")
    others = {i["path"]: i["other"] for i in items if i["other"]}
    todo = [i["path"] for i in items if not i["mine"] and i["path"] not in others]
    if todo:
        try:
            _run(["lock"], cwd=wc, targets=todo, message="APSVN",
                 username=username, password=password, timeout=None,
                 notifier=_notifier(progress, "lock", len(todo), wc)
                 if progress else None)
        except SvnError:
            pass                    # часткова невдача — порахуємо нижче
    after = files_under(wc, rel)
    return {"total": len(items),
            "mine": sum(1 for i in after if i["mine"]),
            "others": others}


def unlock_folder(wc, rel, username=None, password=None, progress=None):
    """Відпустити все, що ми тримаємо в теці."""
    mine = [i["path"] for i in files_under(wc, rel) if i["mine"]]
    if not mine:
        raise SvnError("You do not hold anything in this folder.")
    try:
        _run(["unlock"], cwd=wc, targets=mine, username=username,
             password=password, timeout=None,
             notifier=_notifier(progress, "lock", len(mine), wc)
             if progress else None)
    except SvnError:
        pass
    left = sum(1 for i in files_under(wc, rel) if i["mine"])
    return {"released": len(mine) - left, "left": left}


def cleanup(wc):
    _run(["cleanup", "."], cwd=wc, timeout=None, _retry=False)
    return "Project repaired"


# --- поступ передачі -------------------------------------------------------
#
# Чесно можна показати не все, і вигадувати решту не можна:
#   * качання ОДНІЄЇ версії — точні відсотки: розмір відомий із svn info -r N,
#     а тимчасовий файл росте поступово;
#   * оновлення й перше завантаження — «файл N з M» за рядками виводу;
#   * здача — «N з M підготовлено», а далі svn мовчить. Крапки в
#     «Transmitting file data ....» для цього НЕ годяться: дослід показав одну
#     крапку на 64 МБ, тобто вони не пропорційні обсягу.

_FILE_LINE = re.compile(r"^([ADUGCER])[ADUGCE ]?\s+(.+)$")
_LOCK_LINE = re.compile(r"^'(.+)' (?:locked by user|unlocked)")
_SEND_LINE = re.compile(
    r"^(Adding|Sending|Deleting|Replacing|Adding copy of)\s+(?:\(bin\)\s+)?(.+)$")


_COUNTING = ("prepare", "files")


def _fix_path(wc, shown):
    """Виправити імʼя файлу, яке svn надрукував у чужому кодуванні.

    svn.exe друкує шляхи в cp1251 навіть тоді, коли ACP машини — cp1252, і
    _dec() мовчки читає їх як cp1252: «кадр 00.blend» стає «êàäð 00.blend».
    Виправляємо не здогадкою, а звіркою з диском: підміняємо лише тоді, коли
    виправлене імʼя справді існує.
    """
    if not shown or shown.isascii():
        return shown
    rel = shown.replace("\\", "/")
    if not wc:
        return rel
    if os.path.exists(os.path.join(wc, rel.replace("/", os.sep))):
        return rel
    for enc in ("cp1252", _acp(), "latin-1"):
        try:
            alt = shown.encode(enc).decode("cp1251").replace("\\", "/")
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            continue
        if os.path.exists(os.path.join(wc, alt.replace("/", os.sep))):
            return alt
    return rel


class _Notifier:
    """Перетворює вивід svn на поступ.

    Тримає і лічильник файлів (з рядків), і виміряну швидкість (з лічильників
    вводу-виводу процесу). Швидкість — справжня, а не похідна від вигаданої
    сталої, тому її можна показувати навіть там, де відсотків не буває.
    """

    def __init__(self, cb, kind, total=None, wc=None, total_bytes=None,
                 rate_hint=None):
        self.cb, self.wc = cb, wc
        self.st = {"kind": kind, "phase": "start", "done": 0, "total": total,
                   "file": None, "bytes": None, "total_bytes": total_bytes,
                   "pct": None, "rate": None, "elapsed": 0, "eta": None}
        # rate_hint — швидкість, ЗАМІРЯНА на попередніх передачах цього ж
        # користувача. Лічильники читань для цього не годяться: замір показав
        # 2.00x обсягу для одного великого файлу і 1.00x для сотні дрібних,
        # тобто множник залежить від форми коміту й наперед невідомий.
        self.rate_hint = rate_hint
        self.started = time.monotonic()
        self._prev = None            # (мить, лічильник)

    def push(self):
        st = self.st
        st["elapsed"] = round(time.monotonic() - self.started, 1)
        # Залишок часу — тільки якщо є з чого його порахувати. Оцінка спирається
        # на заміряну раніше швидкість, тому подається як приблизна.
        if (st["phase"] in ("send", "finalize", "prepare")
                and self.rate_hint and st["total_bytes"]):
            st["eta"] = max(0, round(st["total_bytes"] / self.rate_hint
                                     - st["elapsed"]))
        else:
            st["eta"] = None
        # Якщо svn звітує більше, ніж ми очікували, значить наш підрахунок
        # хибний. Тоді краще показати самий лічильник, ніж «файл 2062 з 1».
        if st["total"] and st["done"] > st["total"]:
            st["total"] = None
        # Відсотки лише там, де є що рахувати. На фазі передачі даних svn
        # мовчить, і показувати 100% було б брехнею.
        st["pct"] = (min(100, round(100.0 * st["done"] / st["total"]))
                     if st["total"] and st["phase"] in _COUNTING else None)
        self.cb(dict(st))

    def line(self, line):
        st = self.st
        lk = _LOCK_LINE.match(line)
        if lk:
            st["done"] += 1
            st["file"] = _fix_path(self.wc, lk.group(1).strip())
            st["phase"] = "files"
            self.push()
            return
        send = _SEND_LINE.match(line)
        m = send or _FILE_LINE.match(line)
        if m:
            st["done"] += 1
            st["file"] = _fix_path(self.wc, m.group(2).strip())
            st["phase"] = "prepare" if send else "files"
        elif line.startswith("Transmitting file data"):
            st["phase"] = "send"
            st["file"] = None
        elif line.startswith("Committing transaction"):
            st["phase"] = "finalize"
            st["file"] = None
        else:
            return
        self.push()

    def io(self, nbytes):
        now = time.monotonic()
        if self._prev is None:
            self._prev = (now, nbytes)
            return
        dt = now - self._prev[0]
        if dt < 0.9:                 # згладжуємо, інакше число смикається
            return
        self.st["rate"] = max(0.0, (nbytes - self._prev[1]) / dt)
        self._prev = (now, nbytes)
        self.push()


def _notifier(cb, kind, total=None, wc=None, total_bytes=None,
              rate_hint=None):
    return _Notifier(cb, kind, total, wc, total_bytes, rate_hint)


def _watch_size(dest, total, cb, kind="download"):
    """Стежити, як росте файл, поки svn у нього ллє.

    Єдина передача, де все точно: розмір відомий наперед із `svn info -r N`,
    а байти на диску можна порахувати. Тому і відсотки, і швидкість, і
    залишковий час тут справжні, а не оцінка.
    """
    stop = threading.Event()
    t0 = time.monotonic()
    prev = [t0, 0, None]        # мить, байти, згладжена швидкість

    def run():
        while not stop.wait(0.35):
            try:
                got = os.path.getsize(dest)
            except OSError:
                continue
            now = time.monotonic()
            dt = now - prev[0]
            if dt >= 0.9:
                r = max(0.0, (got - prev[1]) / dt)
                prev[2] = r if prev[2] is None else prev[2] * 0.6 + r * 0.4
                prev[0], prev[1] = now, got
            eta = None
            if prev[2] and total and prev[2] > 1024:
                eta = max(0, round((total - got) / prev[2]))
            cb({"kind": kind, "phase": "receive", "file": os.path.basename(dest),
                "done": None, "total": None, "bytes": got, "total_bytes": total,
                "pct": (min(100, round(100.0 * got / total)) if total else None),
                "rate": prev[2], "elapsed": round(now - t0, 1), "eta": eta})
    threading.Thread(target=run, daemon=True).start()
    return stop


def _local_time(s):
    """svn віддає час за Гринвічем — показувати його художнику не можна."""
    if not s:
        return ""
    try:
        dt = datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=datetime.timezone.utc) \
                 .astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return s[:16].replace("T", " ")


def log(wc, limit=40, username=None, password=None):
    try:
        root = _xml(["log", ".", "-l", str(limit), "-r", "HEAD:1"], cwd=wc,
                    username=username, password=password, timeout=120)
    except SvnError:
        return []
    return [{"rev": e.get("revision"), "author": e.findtext("author") or "?",
             "date": _local_time(e.findtext("date")),
             "msg": (e.findtext("msg") or "").strip()}
            for e in root.findall("logentry")]


# Літери svn -> слова. R («replaced») трапляється, коли файл видалили й одразу
# додали новий із тим самим іменем — для художника це саме «замінено».
CHANGE_WORD = {"A": "added", "M": "changed", "D": "deleted", "R": "replaced"}

REV_FILES_CAP = 500


def revision_files(wc, rev, username=None, password=None, cap=REV_FILES_CAP):
    """Що змінилося в одному коміті.

    ЧОМУ НЕ `svn diff`. Здавалося б, diff і показав би зміни — але на живому
    сервері `svn diff -c N` для одного .blend іде 13 СЕКУНД і повертає 180
    байт «Cannot display: file marked as a binary type»: svn чесно тягне
    обидві ревізії файлу через мережу й аж потім визнає, що показати їх не
    може. У репозиторії художника бінарне майже все, тож панель зависала б на
    кожному кліку. `log -v --xml -r N` дає той самий перелік за 0.1 с і 300
    байт. Виміряно на справжньому сервері; локальний file:// цього не показав
    би взагалі, бо там немає мережі.

    Обрізаємо на cap: первинний імпорт проєкту — це один коміт на кілька тисяч
    шляхів, і малювати їх усі немає ні змоги, ні сенсу.
    """
    try:
        root = _xml(["log", "-v", "--xml", "-r", str(int(rev))], cwd=wc,
                    username=username, password=password, timeout=120)
    except (SvnError, TypeError, ValueError):
        return {"files": [], "total": 0, "truncated": False}

    # Шляхи приходять від кореня СХОВИЩА, а людина бачить свою теку. Якщо копію
    # знято з підтеки, різницю треба відрізати, інакше кожен рядок починався б
    # з чужого префікса.
    prefix = ""
    try:
        nfo = info(wc)
        u, r = (nfo.get("url") or ""), (nfo.get("root") or "")
        if u.startswith(r):
            prefix = u[len(r):]
    except SvnError:
        pass

    out, total = [], 0
    for e in root.findall("logentry"):
        for pe in e.findall("paths/path"):
            total += 1
            if len(out) >= cap:
                continue
            path = (pe.text or "")
            if prefix and path.startswith(prefix):
                path = path[len(prefix):]
            path = path.lstrip("/")
            if not path or JUNK_RE.search(os.path.basename(path)):
                total -= 1
                continue
            act = pe.get("action") or "M"
            out.append({
                "path": path,
                "action": act,
                "action_text": CHANGE_WORD.get(act, act.lower()),
                "kind": pe.get("kind") or "",
                # text-mods=false + prop-mods=true означає «змінилися лише
                # налаштування файлу» — для художника це зовсім інша новина,
                # ніж «файл переробили», і log -v каже це без зайвих запитів
                "props_only": (pe.get("text-mods") == "false"
                               and pe.get("prop-mods") == "true"),
            })
    out.sort(key=lambda x: (x["action"] != "D", x["path"].lower()))
    return {"files": out, "total": total, "truncated": total > len(out)}


def checkout(url, target, username=None, password=None, progress=None):
    os.makedirs(target, exist_ok=True)
    out = _dec(_run(["checkout", url, "."], cwd=target,
                    username=username, password=password, timeout=None,
                    notifier=_notifier(progress, "download", None, target) if progress else None))
    rev = _revision_of(out)
    n = sum(1 for l in out.splitlines() if l[:1] == "A")
    return "Project downloaded%s%s" % (
        (" (commit %s)" % rev) if rev else "",
        (", files: %d" % n) if n else "")


# --- історія окремого файлу й відкат ---------------------------------------
#
# Чому саме так, а не через `svn merge` (перевірено дослідами, tests/exp_*):
#   * merge мовчки пише в read-only файл БЕЗ лока — і навіть тоді, коли файл
#     тримає колега. Диск уже затерто, а коміт падає з E160037. Це проламує
#     всю дисципліну «зайняв/здав», на якій тримається APSVN;
#   * merge конфліктує на бінарнику щоразу, коли у файлі є нездані зміни, і
#     лишає робочу копію в стані, з якого без resolve не вийти;
#   * merge не приймає --targets, тобто кириличний шлях довелося б класти
#     в argv;
#   * `merge -c -N` узагалі не повертає ДО ревізії N — він знімає лише її одну,
#     і людина отримала б не ту версію без жодної помилки.
# Натомість `svn cat` конфліктного стану не має взагалі, віддає байти точно
# і без лока просто безпечно падає, нічого не зіпсувавши.

def _repo_rel(wc, url=None, root=None):
    """Шлях робочої копії від кореня репозиторію ('' якщо копія в корені)."""
    if url is None or root is None:
        i = info(wc)
        url, root = i["url"], i["root"]
    return (url or "")[len(root or ""):].strip("/")


def _quote(repo_rel):
    """URL-компоненти — percent-encoded UTF-8, тобто чистий ASCII.

    Це єдиний спосіб назвати кириличний файл там, де --targets не приймають
    (cat, copy) і де 8.3-псевдоніма не існує (видалений файл).
    """
    return "/".join(urllib.parse.quote(s.encode("utf-8"), safe="")
                    for s in repo_rel.strip("/").split("/") if s)


def file_info(wc, path, rev=None, username=None, password=None):
    """svn info по одному файлу. info приймає --targets — кирилиця безпечна."""
    args = ["info"]
    if rev is not None:
        args += ["-r", str(rev)]
    root = _xml(args, cwd=wc, targets=[path], username=username,
                password=password, timeout=120)
    e = root.find("entry")
    if e is None:
        raise SvnError("This file did not exist yet in that version — "
                       "pick another date.")
    return {"url": e.findtext("url"), "root": e.findtext("repository/root"),
            "size": e.get("size"), "path": e.get("path"),
            "rev": e.get("revision")}


def file_log(wc, path, limit=40, username=None, password=None):
    """Історія ОДНОГО файлу, зі стеженням за перейменуваннями.

    -r HEAD:1 явно: без нього типовий діапазон для шляху робочої копії —
    BASE:1, тобто застаріла копія тихо сховала б свіжі чужі ревізії.
    --stop-on-copy НЕ додавати: вона обрізає історію на перейменуванні.
    """
    try:
        root = _xml(["log", "-v", "-l", str(limit), "-r", "HEAD:1"],
                    cwd=wc, targets=[path], username=username,
                    password=password, timeout=180)
    except SvnError:
        return []

    prefix = _repo_rel(wc)
    cur = "/" + ((prefix + "/") if prefix else "") + path.replace("\\", "/")
    rows = []
    for le in root.findall("logentry"):
        act = frm = None
        for p in le.findall("paths/path"):
            if p.text == cur:
                act = p.get("action")
                frm = p.get("copyfrom-path")
                break
        rows.append({
            "rev": le.get("revision"),
            "author": le.findtext("author") or "?",
            "date": _local_time(le.findtext("date")),
            "msg": (le.findtext("msg") or "").strip(),
            "action": act,
            "renamed_from": (frm or "").lstrip("/") or None,
        })
        # без цього всі ревізії ДО перейменування лишилися б без дії, хоч
        # svn їх чесно віддав: у них файл звався інакше
        if frm:
            cur = frm
    return rows


def is_binary(wc, path, rev=None, username=None, password=None):
    """Чи стоїть на файлі бінарний mime-type.

    Байтова точність `svn cat` тримається саме на ньому: зі svn:eol-style
    cat перекладає кінці рядків, і відкат зіпсував би файл. Для .blend svn
    ставить mime-type сам, але файл, доданий чужим клієнтом, може його не мати.

    Ціль — URL, а не шлях: propget єдиний із потрібних підкоманд НЕ приймає
    --targets, тож кириличне імʼя інакше пішло б у argv.
    """
    try:
        fi = file_info(wc, path, username=username, password=password)
        tgt = _safe_url(fi) + (("@%s" % rev) if rev is not None else "")
        root = _xml(["propget", "svn:mime-type", tgt], cwd=wc,
                    username=username, password=password, timeout=60)
    except (SvnError, ET.ParseError):
        return False
    val = "".join(root.itertext()).strip()
    return bool(val) and not val.startswith("text/")


def _safe_url(fi):
    """Перезібрати URL файлу так, щоб '@' в імені став %40.

    svn у своєму entry/url '@' не екранує, а для peg-ревізії це фатально:
    'http://…/render@2x.png@7' розбирається як peg '2x.png@7'. Тому беремо
    корінь репозиторію і кодуємо кожен компонент самі.
    """
    rel = urllib.parse.unquote((fi["url"] or "")[len(fi["root"] or ""):])
    return "%s/%s" % ((fi["root"] or "").rstrip("/"), _quote(rel))


def _fetch(wc, url_at_rev, dest, username=None, password=None,
           progress=None, total=None):
    """`svn cat <url>@N` потоком у файл. Peg на URL обовʼязковий."""
    stop = _watch_size(dest, total, progress) if progress else None
    try:
        _run(["cat", url_at_rev], cwd=wc, username=username, password=password,
             timeout=None, stdout_to=dest)
    finally:
        if stop is not None:
            stop.set()


def save_revision_as(wc, path, rev, dest, username=None, password=None,
                     progress=None):
    """Покласти стару версію ОКРЕМИМ файлом — нічого не чіпаючи.

    Найбезпечніша з усіх дій: подивитися, як було, не ризикуючи роботою.
    """
    fi = file_info(wc, path, username=username, password=password)
    want = file_info(wc, path, rev=rev, username=username, password=password)
    total = int(want["size"]) if (want.get("size") or "").isdigit() else None
    _fetch(wc, "%s@%s" % (_safe_url(fi), rev), dest,
           username=username, password=password, progress=progress, total=total)
    return dest


def restore_revision(wc, path, rev, me=None, username=None, password=None,
                     rescue_dir=None, progress=None):
    """Зробити стару версію файлу поточною. Історія не переписується.

    Порядок кроків важливий і саме такий не випадково:
      1. ЛОК — він і тільки він ловить застарілу робочу копію (W160042) та
         вкрадений лок ДО того, як ми торкнемося диска;
      2. запасна копія нинішніх байтів, якщо просили;
      3. потік у тимчасовий файл ПОРУЧ + звірка розміру — щоб обрив звʼязку
         не лишив на диску обрізаний .blend, який потім спокійно закомітять;
      4. і лише тоді атомарна підміна.
    """
    full = os.path.join(wc, path.replace("/", os.sep))
    lock(wc, [path], username=username, password=password, me=me)

    saved = rescue_copy(wc, path, rescue_dir)

    fi = file_info(wc, path, username=username, password=password)
    want = file_info(wc, path, rev=rev, username=username, password=password)
    tmp = full + ".apsvn-part"
    exp = int(want["size"]) if (want.get("size") or "").isdigit() else None
    try:
        _fetch(wc, "%s@%s" % (_safe_url(fi), rev), tmp,
               username=username, password=password, progress=progress,
               total=exp)
        got = os.path.getsize(tmp)
        if exp is not None and got != exp:
            raise SvnError(
                "The download broke off: got %d bytes instead of %d. "
                "Your file was not changed — try again." % (got, exp))
        if os.path.exists(full):
            os.chmod(full, 0o666)
        os.replace(tmp, full)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return {"rescue": saved, "size": os.path.getsize(full),
            "was_named": want.get("path")}


def deleted_files(wc, scan=200, username=None, password=None):
    """Файли, які колись були в проєкті, а тепер їх немає.

    Ревізія для відновлення — це (ревізія видалення − 1). Якщо після
    видалення хтось створив файл із тим самим імʼям, запис A мусить скасувати
    попереднього кандидата, інакше APSVN запропонує «повернути» те, що вже є.
    """
    try:
        root = _xml(["log", ".", "-v", "-l", str(scan), "-r", "1:HEAD"],
                    cwd=wc, username=username, password=password, timeout=180)
    except SvnError:
        return []
    prefix = _repo_rel(wc)
    base = "/" + prefix if prefix else ""
    gone = {}
    for le in root.findall("logentry"):             # від старих до новіших
        rev = le.get("revision")
        for p in le.findall("paths/path"):
            full = p.text or ""
            if base and not full.startswith(base + "/"):
                continue
            rel = full[len(base):].lstrip("/")
            if not rel or JUNK_RE.search(os.path.basename(rel)):
                continue
            act = p.get("action")
            if act == "D":
                gone[rel] = {
                    "path": rel, "rev": str(int(rev) - 1), "deleted_in": rev,
                    "kind": p.get("kind") or "",
                    "author": le.findtext("author") or "?",
                    "date": _local_time(le.findtext("date")),
                }
            elif act in ("A", "M", "R"):
                gone.pop(rel, None)
    return sorted(gone.values(), key=lambda x: -int(x["deleted_in"]))


def restore_deleted(wc, repo_rel, rev, username=None, password=None):
    """Повернути видалений файл КОПІЄЮ з ревізії rev — зі збереженням історії.

    Саме copy, а не cat: copy тягне за собою всю попередню історію файлу, тоді
    як cat зробив би новий файл без роду й племені. Ціль — рівно '.', потрібна
    тека задається через cwd: локальний шлях в argv тут класти НЕ МОЖНА (він
    не просто зламався б, а розгорнувся як шаблон і зіпсував робочу копію).
    """
    i = info(wc)
    rel = repo_rel.replace("\\", "/").strip("/")
    parent_rel = os.path.dirname(rel)
    parent_abs = os.path.join(wc, parent_rel.replace("/", os.sep)) if parent_rel else wc
    if not os.path.isdir(parent_abs):
        raise SvnError("The folder “%s” is no longer in the project "
                       "— bring it back first." % parent_rel)
    if os.path.exists(os.path.join(parent_abs, os.path.basename(rel))):
        raise SvnError("A file with that name is already there.")
    prefix = _repo_rel(wc, i["url"], i["root"])
    url = "%s/%s" % (i["root"].rstrip("/"),
                     _quote((prefix + "/" + rel) if prefix else rel))
    _run(["copy", "%s@%s" % (url, rev), "."], cwd=parent_abs,
         username=username, password=password, timeout=None)
    return os.path.basename(rel)


_MOVED = re.compile(r"moved (?:temporarily|permanently) to '([^']+)'", re.I)


def moved_to(err):
    """Нова адреса з помилки E170011, якщо сервер її назвав."""
    m = _MOVED.search(getattr(err, "raw", "") or "")
    return m.group(1).rstrip("/") if m else None


def relocate(wc, new_url, username=None, password=None):
    """Перевести робочу копію на нову адресу сервера.

    Робимо тільки на прямий дозвіл людини: адресу пропонує САМ сервер, а
    йти за чужою вказівкою наосліп не можна.
    """
    _run(["relocate", new_url], cwd=wc, username=username, password=password,
         timeout=300)
    return "The project address has been updated"


def probe_dir(folder):
    """Що вже лежить у теці, куди людина хоче поставити проєкт.

    Нинішній setup() при наявності .svn просто робив update, не звіряючи URL —
    тобто підключення в ЧУЖУ теку проходило без жодної помилки, а config уже
    вказував на інший репозиторій. Це найтихіше з усього знайденого.
    """
    if not os.path.isdir(folder):
        return {"state": "missing"}

    here = os.path.abspath(folder)
    if os.path.isdir(os.path.join(here, ".svn")):
        try:
            e = _xml(["info", "."], cwd=here, timeout=60).find("entry")
            return {"state": "wc", "url": e.findtext("url"),
                    "root": e.findtext("repository/root")}
        except (SvnError, AttributeError):
            return {"state": "broken"}

    # Шукаємо .svn у предках самі, а не через svn info: НЕВЕРСІОНОВАНА тека
    # всередині чужої копії дає E200009 «target doesn't exist», і за помилкою
    # її не відрізнити від порожньої. А підключати проєкт усередину іншого
    # однаково не можна — вкладена копія ламає add і засмічує список файлів.
    p = here
    while True:
        up = os.path.dirname(p)
        if up == p:
            break
        p = up
        if os.path.isdir(os.path.join(p, ".svn")):
            url = None
            try:
                url = _xml(["info", "."], cwd=p, timeout=60).find("entry") \
                          .findtext("url")
            except (SvnError, AttributeError):
                pass
            return {"state": "subdir", "wcroot": p, "url": url}
    return {"state": "empty"}


def set_needs_lock(wc, paths):
    """Разово вішає svn:needs-lock на вже наявні бінарники.

    Значення 'yes', а не '*': svn.exe САМ розгортає шаблони в argv (це не
    cmd.exe), тож '*' перетворювався на список теки і чіпляв needs-lock на
    сторонні файли, а в кириличній теці ще й падав із хибним поясненням
    «це не робоча копія». svn нормалізує будь-яке непорожнє значення до '*',
    тому результат у репозиторії однаковий.
    """
    if not paths:
        return 0
    _run(["propset", "svn:needs-lock", "yes"], cwd=wc, targets=paths, timeout=600)
    return len(paths)


def scan_unprotected(wc):
    """Бінарні файли під версійним контролем без svn:needs-lock.

    Через --xml, а не текстом: текстовий propget друкує кириличні шляхи в
    cp1251 навіть коли ACP машини cp1252, і _dec() робить із них мойбаке.
    Наслідок був тихий — КОЖЕН кириличний бінарник вічно вважався незахищеним,
    а наступний propset падав і мовчки ковтався в setup().
    """
    have = set()
    try:
        root = _xml(["propget", "svn:needs-lock", "-R", "."],
                    cwd=wc, timeout=300)
        for tgt in root.findall("target"):
            p = tgt.get("path") or ""
            # у --xml шляхи абсолютні, а в status --xml — відносні
            if os.path.isabs(p):
                try:
                    p = os.path.relpath(p, wc)
                except ValueError:
                    pass
            have.add(_rel(p.replace("\\", "/")))
    except (SvnError, ET.ParseError):
        pass
    root = _xml(["status", ".", "-v"], cwd=wc, timeout=300)
    need = []
    for tgt in root.findall("target"):
        for e in tgt.findall("entry"):
            p = _rel(e.get("path"))
            ws = e.find("wc-status")
            if ws is None or ws.get("item") in ("unversioned", "ignored", "none"):
                continue
            if not p.lower().endswith(BINARY_EXT):
                continue
            full = os.path.join(wc, p.replace("/", os.sep))
            if os.path.isfile(full) and p not in have:
                need.append(p)
    return need
