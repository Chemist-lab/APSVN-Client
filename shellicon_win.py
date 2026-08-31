# -*- coding: utf-8 -*-
"""Іконки типів файлів з Windows. Фасад живе в shellicon.py.

Цей модуль ВІЛЬНО кликати WinDLL на рівні модуля, бо його імпортують
лише під Windows. Раніше це стояло в спільному файлі — і на маку програма
падала б не в місці виклику, а на самому імпорті, ще до того, як показати
будь-яке вікно.
"""
import ctypes
import os
import struct
import threading
import zlib
from ctypes import wintypes

SIZE = 48                  # 48 px: у списку показується на 18–20, тож при
                           # масштабуванні 125–150 % край лишається чистим

# Розширення Unreal. Ключ — те, що бачить користувач; значення нічого не
# означає, крім «шукати іконку в редакторі, а не в оболонці».
UE_EXT = (".uasset", ".umap", ".uplugin", ".uproject", ".uexp", ".ubulk")

_lock = threading.Lock()
_cache = {}                # ext -> data:URI | None
_tls = threading.local()

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


IID_IImageList = GUID(0x46EB5926, 0x582E, 0x4017,
                      (ctypes.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99,
                                           0x8D, 0xAA, 0x09, 0x50))

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_USEFILEATTRIBUTES = 0x000000010
SHGFI_SYSICONINDEX = 0x000004000
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
SHIL_EXTRALARGE = 2                       # 48 px
ILD_TRANSPARENT = 1

# ПРОТОТИПИ ОБОВʼЯЗКОВІ. Без них ctypes пхає хендл у C int, і виклик падає з
# OverflowError рівно тоді, коли Windows видала хендл більший за 2^31 — тобто
# для одних розширень іконка бралася, для інших ні, без жодної системи.
shell32.SHGetFileInfoW.restype = ctypes.c_void_p
shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.POINTER(SHFILEINFOW), wintypes.UINT,
                                   wintypes.UINT]
shell32.SHGetImageList.restype = ctypes.c_long
shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(GUID),
                                   ctypes.POINTER(ctypes.c_void_p)]
shell32.SHDefExtractIconW.restype = ctypes.c_long
shell32.SHDefExtractIconW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                      wintypes.UINT,
                                      ctypes.POINTER(wintypes.HICON),
                                      ctypes.POINTER(wintypes.HICON),
                                      wintypes.UINT]
user32.GetIconInfo.restype = wintypes.BOOL
user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
user32.DestroyIcon.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetObjectW.restype = ctypes.c_int
gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                            wintypes.UINT, ctypes.c_void_p,
                            ctypes.POINTER(BITMAPINFO), wintypes.UINT]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]


def _co_init():
    """Оболонка вимагає ініціалізованого COM у ПОТОЦІ, який її смикає.

    Розіменування (CoUninitialize) навмисно немає: pywebview кличе нас із
    свого потоку, який живе стільки ж, скільки вікно, а закрити апартамент
    під ним — надійний спосіб зламати все інше, що теж ходить в оболонку.
    """
    if getattr(_tls, "co", False):
        return
    ole32.CoInitializeEx(None, 0x2)       # APARTMENTTHREADED; S_FALSE теж ок
    _tls.co = True


# ------------------------------------------------------------ HICON -> PNG
def _png(w, h, rgba):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def _dib(hdc, hbm, w, h):
    """Пікселі бітмапи як BGRA згори вниз."""
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h            # мінус = перший рядок верхній
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0        # BI_RGB
    buf = (ctypes.c_char * (w * h * 4))()
    if not gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(bmi), 0):
        return None
    return bytearray(buf)


def _hicon_png(hicon):
    """HICON -> PNG. None, якщо щось пішло не так — це не привід падати."""
    ii = ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(ii)):
        return None
    hdc = user32.GetDC(None)
    try:
        bm = BITMAP()
        if not gdi32.GetObjectW(ii.hbmColor, ctypes.sizeof(BITMAP),
                                ctypes.byref(bm)):
            return None
        w, h = int(bm.bmWidth), int(bm.bmHeight)
        if w <= 0 or h <= 0 or w > 512 or h > 512:
            return None
        px = _dib(hdc, ii.hbmColor, w, h)
        if px is None:
            return None

        # Іконка старого зразка не має альфи взагалі — тоді прозорість лежить
        # окремою маскою (біт 1 = крізь неї видно тло). Без цієї гілки такі
        # іконки виходили б чорними квадратами.
        if not any(px[3::4]):
            mask = _dib(hdc, ii.hbmMask, w, h)
            if mask is None:
                return None
            for i in range(0, len(px), 4):
                px[i + 3] = 0 if mask[i] else 255

        for i in range(0, len(px), 4):     # BGRA -> RGBA
            px[i], px[i + 2] = px[i + 2], px[i]
        return _png(w, h, px)
    finally:
        user32.ReleaseDC(None, hdc)
        if ii.hbmColor:
            gdi32.DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            gdi32.DeleteObject(ii.hbmMask)


# ------------------------------------------------------------- джерело 1
def _sys_icon(ext, folder=False):
    """Іконка з оболонки. Файл із таким іменем існувати не мусить."""
    _co_init()
    attrs = FILE_ATTRIBUTE_DIRECTORY if folder else FILE_ATTRIBUTE_NORMAL
    name = "x" if folder else "x" + ext
    sfi = SHFILEINFOW()

    # Спершу пробуємо 48 px зі спільного списку зображень оболонки: SHGFI_ICON
    # дає лише 32, і на масштабуванні 150 % воно помітно мило.
    if shell32.SHGetFileInfoW(name, attrs, ctypes.byref(sfi),
                              ctypes.sizeof(sfi),
                              SHGFI_SYSICONINDEX | SHGFI_USEFILEATTRIBUTES):
        png = _imagelist_icon(sfi.iIcon)
        if png:
            return png

    if not shell32.SHGetFileInfoW(name, attrs, ctypes.byref(sfi),
                                  ctypes.sizeof(sfi),
                                  SHGFI_ICON | SHGFI_LARGEICON
                                  | SHGFI_USEFILEATTRIBUTES):
        return None
    try:
        return _hicon_png(sfi.hIcon)
    finally:
        user32.DestroyIcon(sfi.hIcon)


def _imagelist_icon(idx):
    """48 px зі спільного списку оболонки. COM руками, бо тягнути comtypes
    заради одного виклику — задорого."""
    try:
        pil = ctypes.c_void_p()
        if shell32.SHGetImageList(SHIL_EXTRALARGE, ctypes.byref(IID_IImageList),
                                  ctypes.byref(pil)) != 0 or not pil:
            return None
        vt = ctypes.cast(pil, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        # IImageList: 0..2 — IUnknown, далі Add, ReplaceIcon, SetOverlayImage,
        # Replace, AddMasked, Draw, Remove, і аж тоді GetIcon
        get_icon = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_int, wintypes.UINT,
            ctypes.POINTER(wintypes.HICON))(vt[10])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
        hicon = wintypes.HICON()
        try:
            if get_icon(pil, idx, ILD_TRANSPARENT, ctypes.byref(hicon)) != 0:
                return None
            return _hicon_png(hicon)
        finally:
            if hicon:
                user32.DestroyIcon(hicon)
            release(pil)
    except Exception:
        return None                        # старіша Windows — обійдемось 32 px


# ------------------------------------------------------------- джерело 2
def unreal_editor():
    """Найновіший встановлений UnrealEditor.exe або None.

    Epic лишає шляхи в HKLM\\SOFTWARE\\EpicGames\\Unreal Engine\\<версія>; там
    же осідають збірки з launcher-а. Версії сортуємо числом, а не рядком,
    інакше 5.10 виявиться старшою за 5.9.
    """
    import winreg
    found = []
    for root, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                       (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                       (winreg.HKEY_CURRENT_USER, 0)):
        try:
            key = winreg.OpenKey(root, r"SOFTWARE\EpicGames\Unreal Engine", 0,
                                 winreg.KEY_READ | view)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    ver = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, ver, 0,
                                        winreg.KEY_READ | view) as sub:
                        d = winreg.QueryValueEx(sub, "InstalledDirectory")[0]
                except OSError:
                    continue
                exe = os.path.join(d, "Engine", "Binaries", "Win64",
                                   "UnrealEditor.exe")
                if not os.path.isfile(exe):     # UE4 звався інакше
                    exe = os.path.join(d, "Engine", "Binaries", "Win64",
                                       "UE4Editor.exe")
                if os.path.isfile(exe):
                    try:
                        num = tuple(int(x) for x in ver.split("."))
                    except ValueError:
                        num = (0,)
                    found.append((num, exe))
    return max(found)[1] if found else None


def _exe_icon(path):
    """Головна іконка програми потрібного розміру."""
    _co_init()
    large = wintypes.HICON()
    small = wintypes.HICON()
    try:
        hr = shell32.SHDefExtractIconW(path, 0, 0, ctypes.byref(large),
                                       ctypes.byref(small), (16 << 16) | SIZE)
    except Exception:
        return None
    if hr != 0 or not large:
        return None
    try:
        return _hicon_png(large)
    finally:
        user32.DestroyIcon(large)
        if small:
            user32.DestroyIcon(small)


# --- імена, під якими це бере фасад ------------------------------
# Однакові для обох систем, щоб shellicon.py не знав, кого саме він
# імпортував.
sys_icon = _sys_icon
app_icon = _exe_icon
