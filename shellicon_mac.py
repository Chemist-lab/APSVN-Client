# -*- coding: utf-8 -*-
"""Іконки типів файлів з macOS. Фасад живе в shellicon.py.

НЕ ЗАПУСКАНО НА СПРАВЖНЬОМУ МАКУ. Писалося з Windows, тож ставитися до нього
треба як до чернетки, яку належить перевірити першою ж на маку. Саме тому все
тут обгорнуте так, щоб будь-яка несподіванка поверталася як None: інтерфейс
тоді малює свій значок, і програма працює далі. Іконка — оздоблення, вона не
має права нічого ламати.

Чому це взагалі окремо від Windows: там оболонка віддає HICON, який доводиться
руками розбирати на пікселі через GDI. Тут NSWorkspace одразу дає NSImage, а
той сам уміє віддати PNG — коду вчетверо менше.

Що на маку відрізняється по суті:
* `.blend` система знає, якщо стоїть Blender.app — він оголошує цей тип у
  своєму Info.plist, так само як на Windows це робить реєстр;
* Unreal свої розширення не оголошує ТУТ ТЕЖ, тож для .uasset/.umap іконку
  беремо з самого UnrealEditor.app;
* застосунки шукаємо в /Applications, а не в реєстрі — реєстру немає.
"""
import os

SIZE = 48

UE_EXT = (".uasset", ".umap", ".uplugin", ".uproject", ".uexp", ".ubulk")

_MAC_APPS = ("/Applications", os.path.expanduser("~/Applications"),
             "/Applications/Epic Games")


def _appkit():
    """PyObjC вантажимо ліниво: якщо його в збірці немає, програма має
    працювати без іконок, а не падати на імпорті."""
    try:
        from AppKit import NSWorkspace, NSBitmapImageRep, NSImage  # noqa: F401
        from Foundation import NSMakeSize                          # noqa: F401
        return True
    except Exception:
        return False


def _png_from_nsimage(img):
    """NSImage -> PNG-байти потрібного розміру."""
    from AppKit import NSBitmapImageRep
    from Foundation import NSMakeSize
    try:
        img.setSize_(NSMakeSize(SIZE, SIZE))
        data = img.TIFFRepresentation()
        if data is None:
            return None
        rep = NSBitmapImageRep.imageRepWithData_(data)
        if rep is None:
            return None
        # 4 == NSPNGFileType. Стала, а не імпорт: у різних версіях PyObjC вона
        # лежить у різних місцях, і промахнутися імпортом тут легше, ніж
        # написати число.
        out = rep.representationUsingType_properties_(4, None)
        return bytes(out) if out else None
    except Exception:
        return None


def sys_icon(ext, folder=False):
    """Іконка типу файлу від системи. Файл існувати не мусить."""
    if not _appkit():
        return None
    try:
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        if folder:
            # Іконка теки береться від справжньої теки, яка точно є: питати
            # тип "public.folder" через застарілий API — лотерея між версіями.
            img = ws.iconForFile_("/")
        else:
            img = ws.iconForFileType_(ext.lstrip("."))
        return _png_from_nsimage(img) if img else None
    except Exception:
        return None


def app_icon(app_path):
    """Іконка застосунку — для типів, яких система не знає."""
    if not _appkit() or not app_path:
        return None
    try:
        from AppKit import NSWorkspace
        img = NSWorkspace.sharedWorkspace().iconForFile_(app_path)
        return _png_from_nsimage(img) if img else None
    except Exception:
        return None


def unreal_editor():
    """Найновіший UnrealEditor.app або None.

    Реєстру тут немає, тож просто дивимось у теки застосунків. Версії
    сортуємо числом, а не рядком, інакше 5.10 виявиться старшою за 5.9 —
    та сама пастка, що й у віконній гілці.
    """
    found = []
    for root in _MAC_APPS:
        if not os.path.isdir(root):
            continue
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            if not name.startswith("UE_"):
                continue
            app = os.path.join(root, name, "Engine", "Binaries", "Mac",
                               "UnrealEditor.app")
            if not os.path.isdir(app):
                app = os.path.join(root, name, "Engine", "Binaries", "Mac",
                                   "UE4Editor.app")
            if os.path.isdir(app):
                try:
                    num = tuple(int(x) for x in name[3:].split("."))
                except ValueError:
                    num = (0,)
                found.append((num, app))
    return max(found)[1] if found else None
