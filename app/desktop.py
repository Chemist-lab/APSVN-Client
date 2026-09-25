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

# Корінь установки — тека, у якій лежать app/, ui/, runtime/, svn/, vendor/.
# ЄДИНЕ місце, де це рахується. Раніше кожен модуль брав власну теку й від неї
# шукав сусідів; щойно код переїхав на рівень нижче, кожне таке місце стало б
# окремою поламкою, і всі — мовчазними: svn «не знайдено», ui не відкривається,
# іконки немає. Рахуємо один раз, від цього файлу, і всі беруть звідси.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


# ----------------------------------------------------------- буфер обміну
def copy_text(text):
    """Покласти текст у буфер обміну системи. True — вдалося.

    Не через navigator.clipboard у вебвʼю: той вимагає фокуса документа й
    дозволу, і відмовляє мовчки саме тоді, коли людина клікнула пункт меню,
    яке вже закрилося. Тут — пряма дорога, однакова з будь-якого потоку.
    """
    text = str(text or "")
    try:
        if WINDOWS:
            return _win_clipboard(text)
        if MAC:
            # pbcopy читає stdin у кодуванні локалі; без UTF-8 кирилиця в
            # шляху стала б знаками питання
            r = subprocess.run(["pbcopy"], input=text.encode("utf-8"),
                               env=dict(os.environ, LANG="en_US.UTF-8"),
                               check=False)
            return r.returncode == 0
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
            try:
                r = subprocess.run(cmd, input=text.encode("utf-8"), check=False)
                if r.returncode == 0:
                    return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def _clip_api():
    """user32/kernel32 з ОГОЛОШЕНИМИ типами — див. README про shellicon: без
    argtypes дескриптор понад 2^31 падає з OverflowError, і не щоразу."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.OpenClipboard.restype = wintypes.BOOL
    u.EmptyClipboard.argtypes = []
    u.EmptyClipboard.restype = wintypes.BOOL
    u.CloseClipboard.argtypes = []
    u.CloseClipboard.restype = wintypes.BOOL
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = wintypes.HANDLE
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.restype = wintypes.BOOL
    k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    k.GlobalFree.restype = wintypes.HGLOBAL
    return ctypes, u, k


def _open_clipboard(u):
    import time
    # буфер може на мить тримати інша програма (менеджер буфера, RDP) —
    # кілька спроб поспіль, а не одна відмова
    for _ in range(20):
        if u.OpenClipboard(None):
            return True
        time.sleep(0.03)
    return False


def _win_clipboard(text):
    ctypes, u, k = _clip_api()
    data = (text + "\0").encode("utf-16-le")
    if not _open_clipboard(u):
        return False
    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
        if not h:
            return False
        ptr = k.GlobalLock(h)
        if not ptr:
            k.GlobalFree(h)
            return False
        ctypes.memmove(ptr, data, len(data))
        k.GlobalUnlock(h)
        if not u.SetClipboardData(13, h):              # CF_UNICODETEXT
            k.GlobalFree(h)                            # не взяли — звільняємо самі
            return False
        return True                                    # тепер пам'ять належить системі
    finally:
        u.CloseClipboard()


def read_clipboard_text():
    """Текст із буфера — для перевірок (і щоб повернути людині її буфер)."""
    try:
        if WINDOWS:
            ctypes, u, k = _clip_api()
            if not _open_clipboard(u):
                return None
            try:
                h = u.GetClipboardData(13)
                if not h:
                    return None
                ptr = k.GlobalLock(h)
                if not ptr:
                    return None
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    k.GlobalUnlock(h)
            finally:
                u.CloseClipboard()
        if MAC:
            r = subprocess.run(["pbpaste"], capture_output=True, check=False,
                               env=dict(os.environ, LANG="en_US.UTF-8"))
            return r.stdout.decode("utf-8", "replace")
    except Exception:
        pass
    return None


# ------------------------------------------------ перетягування файлів назовні
def drag_supported(window):
    """Чи вміємо ми потягнути СПРАВЖНІ файли з вікна в іншу програму.

    Лише Windows: там вікно pywebview — форма WinForms, і в неї є звичайний
    DoDragDrop, той самий, яким тягне файли Провідник. На маку для цього
    потрібна сесія перетягування AppKit із подією миші в руках, а з мосту
    JS→Python подія приходить уже без неї; зробити це наосліп, без мака під
    рукою, означало б ризикнути падінням програми. Там перенос між теками
    працює засобами самої сторінки, а в Blender — через «Copy path».
    """
    return bool(WINDOWS and window is not None
                and getattr(window, "native", None) is not None)


def _winforms():
    """WinForms через pythonnet. У програмі їх уже підняв pywebview, але
    покладатися на це не можна: тести й будь-який інший виклик ідуть без
    вікна, і `from System import …` там падав би ModuleNotFoundError."""
    import clr
    clr.AddReference("System.Windows.Forms")


def file_drop_data(paths):
    """Об'єкт перетягування: самі файли (CF_HDROP) і, запасом, шляхи текстом.

    Файли — для Blender і Провідника: Blender бере саме CF_HDROP. Текст — для
    будь-якого поля введення, куди людина захоче кинути шлях.
    """
    _winforms()
    from System import Array, String
    from System.Windows.Forms import DataFormats, DataObject
    data = DataObject()
    data.SetData(DataFormats.FileDrop, Array[String](list(paths)))
    data.SetData(DataFormats.UnicodeText, "\r\n".join(paths))
    return data


def _drag_on_ui(form, paths):
    """Сам DoDragDrop. Лише в потоці вікна (його робить drag_files)."""
    _winforms()
    from System.Windows.Forms import Control, DragDropEffects, MouseButtons
    # КНОПКУ ВЖЕ ВІДПУСТИЛИ — НЕ ПОЧИНАЄМО. Виклик доходить сюди через міст за
    # десятки мілісекунд; якщо людина лише смикнула мишу, кнопка вже вгорі, а
    # OLE у такому разі не скасовує перетягування, а КИДАЄ файл туди, де зараз
    # курсор, — хоч на робочий стіл. Випадкова копія сцени деінде — не те, що
    # людина мала на увазі.
    if not int(Control.MouseButtons) & int(MouseButtons.Left):
        return "cancelled"
    # Лише копіювати або посилатися — ніколи не ПЕРЕНОСИТИ. Дозволь ми Move,
    # і Провідник на тому самому диску забрав би файл із робочої копії
    # (для CF_HDROP переносить сам той, куди кинули), а svn побачив би, що
    # файл зник. Перенос у межах проєкту робимо ми самі, через svn move.
    effect = int(form.DoDragDrop(file_drop_data(paths),
                                 DragDropEffects.Copy | DragDropEffects.Link))
    if effect & int(DragDropEffects.Copy):
        return "copy"
    if effect & int(DragDropEffects.Link):
        return "link"
    return "none"


def drag_files(window, paths):
    """Потягнути файли з вікна — у Blender, у Провідник, на свою ж теку.

    Блокує до кидка. 'copy' | 'link' | 'none' | 'cancelled'; None — на цій
    системі не вміємо (див. drag_supported).
    """
    if not drag_supported(window):
        return None
    form = window.native
    from System import Func, Type
    out = {}

    def run():
        try:
            out["r"] = _drag_on_ui(form, paths)
        except Exception as e:                 # нічого не має валити вікно
            out["r"] = "error"
            out["e"] = str(e)
        return None

    form.Invoke(Func[Type](run))
    return out.get("r", "none")


# --------------------------------------------------------------- де ми живемо
def app_bundle(path):
    """Тека .app, усередині якої лежить path, або None.

    Потрібна оновленню. На маку програма — це bundle ЦІЛКОМ: у ньому і свій
    Python, і свій svn, і підпис, а код лежить усередині, в Contents/Resources.
    Підмінити саму теку з кодом означало б лишити покалічений bundle — новий
    код зі старим рантаймом і зламаною пломбою. Поза bundle (запуск із
    вихідників) відповіді немає, і це не помилка, а звичайний стан розробника.
    """
    if not MAC:
        return None
    d = os.path.abspath(path)
    while True:
        if d.endswith(".app") and os.path.isdir(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


# ------------------------------------------------------- іконка вікна
def set_window_icon(title, ico_path):
    """Поставити іконку вікна — вона ж і на панелі задач.

    ЧОМУ ЦЕ ОКРЕМА РОБОТА. Вікно малює pywebview, а сам процес — це pythonw з
    теки runtime, тож панель задач показує логотип Python, хоч у самого
    APSVN.exe іконка вже наша. Ці дві іконки беруться з різних місць: у
    Провіднику — з ресурсів exe, на панелі задач — з ВІКНА.

    Вікно шукаємо за заголовком, бо pywebview не віддає його дескриптор. Це
    єдине незручне місце, і воно не страшне: помилитися можна хіба з іншим
    вікном, яке зветься так само, а невдача тут коштує лише чужої іконки.

    Поза Windows нічого не робимо: на маку іконку несе сам bundle.
    """
    if not WINDOWS or not os.path.isfile(ico_path):
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.FindWindowW.restype = wintypes.HWND
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                 wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                 wintypes.UINT]
        u.SendMessageW.restype = ctypes.c_void_p
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   ctypes.c_void_p, ctypes.c_void_p]
        hwnd = u.FindWindowW(None, title)
        if not hwnd:
            return False
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
        WM_SETICON = 0x0080
        # Два розміри окремо: маленький іде в заголовок і Alt+Tab, великий —
        # на панель задач. Одного не досить, Windows не масштабує його сама.
        for which, cx, cy in ((0, 16, 16), (1, 32, 32)):
            h = u.LoadImageW(None, ico_path, IMAGE_ICON, cx, cy,
                             LR_LOADFROMFILE)
            if h:
                u.SendMessageW(hwnd, WM_SETICON,
                               ctypes.c_void_p(which), ctypes.c_void_p(h))
        return True
    except Exception:
        return False


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
