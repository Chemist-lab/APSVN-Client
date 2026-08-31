# -*- coding: utf-8 -*-
"""Усе, що залежить від операційної системи — в одному місці.

Решта APSVN не має права знати, під чим вона працює. Доти, доки виклики до
Windows розкидані по app.py і svn_client.py, будь-який порт означає полювання
на них по всьому коду, а кожен пропущений вилазить не помилкою збірки, а
падінням у художника.

Про кожну розбіжність нижче написано, ЧОМУ вона є, а не просто «на маку
інакше»: половина з них не очевидна, поки не наступиш.
"""
import os
import subprocess
import sys

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"


# ------------------------------------------------------------------- запуск
def no_window():
    """Аргументи Popen, щоб виклик svn не блимав вікном консолі.

    ТУТ БУЛА МІНА. Раніше стояло
        _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    і на будь-якій не-Windows системі getattr не знаходив атрибута, віддавав
    число за замовчуванням — а POSIX-гілка Popen кидає на нього
    ValueError: creationflags is only supported on Windows platforms.
    Тобто найперший же виклик svn на маку падав, і не там, де шукали б.
    """
    if not WINDOWS:
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW",
                                     0x08000000)}


# ---------------------------------------------------------------- налаштування
def conf_dir(name="APSVN"):
    """Тека налаштувань за правилами тієї системи, де ми зараз.

    На маку це ~/Library/Application Support, а не крапкова тека в домівці:
    крапкові теки Finder ховає, і художник, якому сказали «покажи мені свій
    config.json», їх просто не знайде.
    """
    if WINDOWS:
        return os.path.join(os.environ.get("APPDATA", "."), name)
    if MAC:
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", name)
    return os.path.join(
        os.environ.get("XDG_CONFIG_HOME",
                       os.path.join(os.path.expanduser("~"), ".config")), name)


# -------------------------------------------------------- відкриття і показ
def open_path(path):
    """Відкрити файл чи теку тим, чим система вважає за потрібне."""
    try:
        if WINDOWS:
            os.startfile(path)              # noqa: S606 - лише на Windows
        elif MAC:
            subprocess.run(["open", path], check=False, **no_window())
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception:
        return False


def reveal(path):
    """Показати файл у провіднику, ВИДІЛИВШИ його.

    Не те саме, що відкрити теку: художник просив показати конкретний файл, а
    в теці на дві тисячі елементів шукати його очима — окрема робота.
    """
    try:
        if WINDOWS:
            # /select, вимагає саме такого написання (кома притулена) і не
            # терпить лапок навколо всього аргументу
            subprocess.run(["explorer", "/select,", os.path.normpath(path)],
                           check=False, **no_window())
        elif MAC:
            subprocess.run(["open", "-R", path], check=False)
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
        return True
    except Exception:
        return False


def message_box(title, text, warn=False):
    """Останній рубіж: сказати людині, чому програма не піднялася.

    Викликається тоді, коли інтерфейсу ще (або вже) немає, тож покластися
    можна лише на саму систему.
    """
    try:
        if WINDOWS:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title,
                                             0x30 if warn else 0x10)
            return True
        if MAC:
            # osascript, а не Tk: Tk у збірці немає, а тягнути його заради
            # одного віконця з помилкою — сотні мегабайтів
            script = ('display dialog %s with title %s buttons {"OK"} '
                      'default button 1 with icon %s'
                      % (_as(text), _as(title),
                         "caution" if warn else "stop"))
            subprocess.run(["osascript", "-e", script], check=False)
            return True
    except Exception:
        pass
    print("%s: %s" % (title, text), file=sys.stderr)
    return False


def _as(s):
    """Рядок для AppleScript. Лапки й зворотні слеші екрануються, інакше
    повідомлення з шляхом C:\\... ламає сам скрипт."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ------------------------------------------------------------------ пошук svn
def svn_candidates(app_dir):
    """Де шукати svn, від найбажанішого до найвипадковішого.

    Своя збірка поруч із програмою — завжди перша: чужий svn у PATH може бути
    старим, зібраним без serf (тобто без https) або взагалі іншої версії, і
    з'ясується це щонайпізніше — під час першої мережевої дії у художника.
    """
    if WINDOWS:
        return [os.path.join(app_dir, "svn", "svn.exe"),
                r"C:\Program Files\SlikSvn\bin\svn.exe",
                r"C:\Program Files (x86)\SlikSvn\bin\svn.exe",
                r"C:\Program Files\TortoiseSVN\bin\svn.exe",
                r"C:\Program Files\Subversion\bin\svn.exe"]
    if MAC:
        return [os.path.join(app_dir, "svn", "bin", "svn"),
                os.path.join(app_dir, "svn", "svn"),
                "/opt/homebrew/bin/svn",        # Apple Silicon
                "/usr/local/bin/svn",           # Intel
                "/usr/bin/svn"]                 # до Xcode 11; далі його немає
    return [os.path.join(app_dir, "svn", "svn"), "/usr/bin/svn",
            "/usr/local/bin/svn"]
