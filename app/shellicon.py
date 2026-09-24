# -*- coding: utf-8 -*-
"""Іконки типів файлів — із самої системи, а не з комплекту APSVN.

Художник має бачити, що `.blend` — це блендер, а `.uasset` — Unreal, а не
однаковий сірий аркуш на весь список.

ЧОМУ НЕ ПОКЛАСТИ КАРТИНКИ В РЕПОЗИТОРІЙ. По-перше, логотипи Blender і Unreal
захищені, і роздавати їх у складі чужої програми — не наша справа. По-друге,
іконка з системи ЗАВЖДИ правильна: у людини стоїть Blender 3.6 — буде іконка
3.6, стоїть 4.2 — буде 4.2, не стоїть зовсім — буде чесний сірий аркуш, а не
обіцянка того, чого на машині немає.

Два джерела, бо одного не вистачає, і це справджується на ОБОХ системах:
* оболонка знає `.blend`, `.png`, `.psd`, `.fbx`, теки — усе, що оголошено
  встановленими програмами (реєстр на Windows, Info.plist застосунків на маку);
* Unreal Engine свої розширення не оголошує ніде (перевірено на Windows:
  `.uasset`, `.umap`, `.uplugin` — «not registered»), тож для них іконку
  дістаємо з самого редактора.

Цей файл — лише фасад: нормалізація, кеш і рішення «коли лізти в редактор».
Уся робота з системою — у shellicon_win.py / shellicon_mac.py, і саме тому
імпорт нижче умовний. Раніше WinDLL стояв на рівні спільного модуля, і на маку
програма впала б на самому імпорті, ще до першого вікна.

Порожній результат — не помилка: інтерфейс просто лишає свій значок.
"""
import base64
import threading

import desktop

if desktop.WINDOWS:
    import shellicon_win as _sys
elif desktop.MAC:
    import shellicon_mac as _sys
else:
    _sys = None

UE_EXT = (".uasset", ".umap", ".uplugin", ".uproject", ".uexp", ".ubulk")

_lock = threading.Lock()
_cache = {}                # ext -> data:URI | None


def unreal_editor():
    """Шлях до встановленого редактора Unreal або None."""
    if _sys is None:
        return None
    try:
        return _sys.unreal_editor()
    except Exception:
        return None


def _generic():
    """Іконка, яку система дає невідомому розширенню.

    Потрібна як еталон: якщо `.uasset` виглядає точно так само, значить
    система нічого про нього не знає — і тоді має сенс лізти в редактор.
    """
    if "*" not in _cache:
        _cache["*"] = _sys.sys_icon(".zzqq-nothing-claims-this") \
            if _sys else None
    return _cache["*"]


def _build(ext):
    if _sys is None:
        return None
    if ext == "<dir>":
        return _sys.sys_icon("", folder=True)
    png = _sys.sys_icon(ext)
    if ext in UE_EXT and (png is None or png == _generic()):
        app = unreal_editor()
        if app:
            png = _sys.app_icon(app) or png
    return png


def icon(ext):
    """data:URI для розширення (`.blend`) або `<dir>`; None — немає чого дати."""
    # Список приходить з інтерфейсу, тобто з JSON — туди легко залітає
    # число чи null. Іконка — оздоблення, вона не має права валити список файлів.
    ext = str(ext if ext is not None else "").strip().lower()
    if not ext:
        return None
    if not ext.startswith(".") and ext != "<dir>":
        ext = "." + ext
    with _lock:
        if ext in _cache:
            return _cache[ext]
    try:
        png = _build(ext)
    except Exception:
        png = None
    uri = ("data:image/png;base64,"
           + base64.b64encode(png).decode("ascii")) if png else None
    with _lock:
        _cache[ext] = uri
    return uri


def icons(exts):
    """{розширення: data:URI} — без тих, для яких нічого не знайшлось."""
    out = {}
    for e in list(exts or [])[:200]:       # список приходить із інтерфейсу
        u = icon(e)
        if u:
            out[str(e).lower()] = u
    return out
