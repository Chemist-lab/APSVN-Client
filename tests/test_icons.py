# -*- coding: utf-8 -*-
"""Іконки типів файлів із Windows.

Найдорожча помилка тут була не в логіці, а в ctypes: без явних прототипів
хендл вікна/бітмапи пхався в C int, і виклик падав з OverflowError рівно
тоді, коли Windows видала хендл більший за 2^31. Наслідок — для одних
розширень іконка бралася, для інших ні, і жодної системи в цьому не було.
Тому перевірки нижче ганяють ДЕСЯТКИ розширень підряд, а не одне: одне могло
б пощастити.
"""
import base64
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import shellicon as si

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (" | " + str(detail) if detail else ""))


def png_of(uri):
    """data:URI -> (ширина, висота, байти) або None."""
    if not uri:
        return None
    if not uri.startswith("data:image/png;base64,"):
        return None
    b = base64.b64decode(uri.split(",", 1)[1])
    if b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", b[16:24])
    return w, h, b


print("=" * 62)
print("1. Що взагалі віддається")
print("=" * 62)
u = si.icon(".txt")
p = png_of(u)
check("для звичайного розширення є PNG", p is not None, (u or "")[:40])
check("розмір 48x48", p and p[0] == 48 and p[1] == 48, p and p[:2])
check("це data:URI, а не шлях", (u or "").startswith("data:image/png;base64,"))

print()
print("=" * 62)
print("2. Прототипи ctypes: жодного розширення не загубили")
print("=" * 62)
# Саме тут ловився OverflowError на великих хендлах — по одному розширенню
# баг був невидимий.
many = [".txt", ".png", ".jpg", ".psd", ".fbx", ".obj", ".exe", ".dll",
        ".zip", ".pdf", ".mp4", ".wav", ".json", ".xml", ".py", ".bat",
        ".blend", ".uasset", ".umap", ".uproject", ".abc", ".exr", ".tga",
        ".mov", ".ma", ".mb", ".max", ".spp", ".ztl", ".hip"]
got = si.icons(many)
bad = [e for e in many if e in got and png_of(got[e]) is None]
check("жодна віддана іконка не побита", not bad, bad)
check("більшість розширень щось дала", len(got) >= len(many) * 0.7,
      "%d з %d" % (len(got), len(many)))
sizes = {png_of(got[e])[:2] for e in got}
check("усі одного розміру", len(sizes) == 1, sizes)

print()
print("=" * 62)
print("3. Blender і Unreal")
print("=" * 62)
generic = si._generic()
blend = si.icon(".blend")
check("для .blend є іконка", blend is not None)
if blend and generic:
    check("і вона НЕ сірий аркуш невідомого типу",
          base64.b64decode(blend.split(",", 1)[1]) != generic,
          "Blender не встановлено?")

exe = si.unreal_editor()
print("  UnrealEditor:", exe or "не знайдено")
if exe:
    check("знайдений редактор існує на диску", os.path.isfile(exe), exe)
    ua = si.icon(".uasset")
    check("для .uasset є іконка", ua is not None)
    if ua and generic:
        # .uasset Windows не знає взагалі — ця іконка МУСИТЬ прийти з редактора
        check("для .uasset підтягнули іконку з редактора, а не заглушку",
              base64.b64decode(ua.split(",", 1)[1]) != generic)
    check(".umap виглядає так само, як .uasset", si.icon(".umap") == ua)
else:
    check("без UE .uasset тихо віддає що є (не падає)",
          si.icon(".uasset") is None or png_of(si.icon(".uasset")))

print()
print("=" * 62)
print("4. Теки й дурні запити")
print("=" * 62)
d = png_of(si.icon("<dir>"))
check("тека має свою іконку", d is not None)
check("тека НЕ виглядає як файл", si.icon("<dir>") != si.icon(".txt"))
check("невідоме розширення не ламає нічого",
      png_of(si.icon(".zzqq-nobody-claims-this")) is not None)
check("порожній запит віддає порожнє", si.icons([]) == {})
check("None замість списку не валить", si.icons(None) == {})
check("сміття в списку не валить",
      isinstance(si.icons([None, 123, "", "blend"]), dict))
check("розширення без крапки теж працює", si.icon("blend") == si.icon(".blend"))
check("регістр не має значення", si.icon(".BLEND") == si.icon(".blend"))

print()
print("=" * 62)
print("5. Памʼять: питаємо систему один раз")
print("=" * 62)
si.icon(".blend")                                   # прогріли
n = len(si._cache)
si.icons([".blend", ".blend", ".BLEND"])
check("повтори не плодять записів у кеші", len(si._cache) == n, len(si._cache))
check("«нічого немає» теж памʼятається (щоб не питати щоразу)",
      ".zzqq-nobody-claims-this" in si._cache)

print()
print("=" * 62)
print("ПРОЙДЕНО: %d   ПРОВАЛЕНО: %d" % (len(OK), len(FAIL)))
if FAIL:
    print("Провалені:", ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
