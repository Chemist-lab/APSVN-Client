# -*- coding: utf-8 -*-
"""Іконки типів файлів з macOS. Фасад живе в shellicon.py.

Чому це взагалі окремо від Windows: там оболонка віддає HICON, який доводиться
руками розбирати на пікселі через GDI. Тут NSWorkspace одразу дає NSImage, а
той сам уміє віддати PNG — коду вчетверо менше.

Що на маку відрізняється по суті:
* `.blend` система знає, якщо стоїть Blender.app — він оголошує цей тип у
  своєму Info.plist, так само як на Windows це робить реєстр. Перевірено:
  UTI виходить org.blenderfoundation.blender.file, іконка своя;
* Unreal свої розширення не оголошує ТУТ ТЕЖ — `.uasset` дає динамічний
  `dyn.ah62d4rv4ge81n2pxsrw1k`, тобто «ніхто цього типу не заявив», і іконка
  приходить та сама, що для вигаданого розширення. Саме на це й спирається
  _generic() у фасаді, тож для .uasset/.umap іконку беремо з UnrealEditor.app;
* застосунки шукаємо в /Applications, а не в реєстрі — реєстру немає.

Усе обгорнуте так, щоб будь-яка несподіванка поверталася як None: інтерфейс
тоді малює свій значок, і програма працює далі. Іконка — оздоблення, вона не
має права нічого ламати.
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
        from AppKit import (NSWorkspace, NSBitmapImageRep,      # noqa: F401
                            NSGraphicsContext, NSDeviceRGBColorSpace)
        from Foundation import NSMakeSize, NSMakeRect           # noqa: F401
        return True
    except Exception:
        return False


def _png_from_nsimage(img):
    """NSImage -> PNG-байти РІВНО SIZE x SIZE.

    Тут була пастка. Спокусливо зробити setSize_() і взяти TIFFRepresentation,
    але setSize_ міняє лише логічний розмір: у TIFF лягають УСІ представлення,
    і imageRepWithData_ дістає з них найбільше. Виміряно: TIFF на 36.9 МБ і
    PNG 1024x1024 на 159 КБ замість очікуваних двох кілобайтів — а таких
    іконок список просить до тридцяти, і всі вони їдуть через міст у
    javascript. Тому малюємо у власний растр потрібного розміру: 2 КБ.
    """
    from AppKit import (NSBitmapImageRep, NSGraphicsContext,
                        NSDeviceRGBColorSpace)
    from Foundation import NSMakeSize, NSMakeRect, NSZeroRect
    try:
        rep = NSBitmapImageRep.alloc().\
            initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
                None, SIZE, SIZE, 8, 4, True, False,
                NSDeviceRGBColorSpace, 0, 0)
        if rep is None:
            return None
        rep.setSize_(NSMakeSize(SIZE, SIZE))
        NSGraphicsContext.saveGraphicsState()
        try:
            NSGraphicsContext.setCurrentContext_(
                NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
            # 2 == NSCompositingOperationSourceOver: іконки з альфою, і без
            # цього прозоре тло стало б чорним квадратом.
            img.drawInRect_fromRect_operation_fraction_(
                NSMakeRect(0, 0, SIZE, SIZE), NSZeroRect, 2, 1.0)
        finally:
            NSGraphicsContext.restoreGraphicsState()
        # 4 == NSPNGFileType. Стала, а не імпорт: у різних версіях PyObjC вона
        # лежить у різних місцях, і промахнутися імпортом тут легше, ніж
        # написати число. Перевірено дослідом — на виході справді PNG.
        out = rep.representationUsingType_properties_(4, None)
        return bytes(out) if out else None
    except Exception:
        return None


def _image_for_ext(ws, ext):
    """NSImage для розширення.

    iconForFileType_ застарілий з macOS 12 — працює й досі (перевірено на 27),
    але одного дня зникне. Тож спершу сучасний шлях через UTType, а
    застарілий лишається запасним: якщо в цій збірці немає
    UniformTypeIdentifiers, краще стара робоча функція, ніж порожній список
    іконок.
    """
    try:
        from UniformTypeIdentifiers import UTType
        t = UTType.typeWithFilenameExtension_(ext)
        if t is not None:
            return ws.iconForContentType_(t)
    except Exception:
        pass
    return ws.iconForFileType_(ext)


def _image_for_folder(ws):
    """NSImage теки.

    НЕ iconForFile_("/"): корінь — це том, і система дає йому іконку
    жорсткого диска, а не теки. У списку файлів це виглядало б просто
    неправильно.
    """
    try:
        from UniformTypeIdentifiers import UTType
        t = UTType.typeWithIdentifier_("public.folder")
        if t is not None:
            return ws.iconForContentType_(t)
    except Exception:
        pass
    # Запасний шлях — звичайна тека, яка є на кожному маку.
    return ws.iconForFile_("/Library")


def sys_icon(ext, folder=False):
    """Іконка типу файлу від системи. Файл існувати не мусить."""
    if not _appkit():
        return None
    try:
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        img = _image_for_folder(ws) if folder \
            else _image_for_ext(ws, ext.lstrip("."))
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
