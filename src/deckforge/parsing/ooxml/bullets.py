"""Маркер списка первого уровня из мастера. Change (4) `theme-extraction`.

Маркер — часть дизайн-системы шаблона: знак, гарнитура, цвет и глубина выноса заданы
автором наравне с палитрой и шкалой. Плейсхолдер их наследует сам, а свободный текстбокс
не наследует ничего, и без этих сведений список выглядит набором абзацев
(прогон 2ac85990b2f2).

Читается только первый уровень: свободные блоки одноуровневые по построению — вложенность
в них задаёт `BulletItem.level`, а до второго уровня наш композитор ещё не доходил.
"""

from __future__ import annotations

from lxml import etree

from deckforge.domain.enums import ColorRef
from deckforge.domain.template import BulletStyle, ThemeColors
from deckforge.parsing.ooxml.theme import nearest_color_ref

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def parse_bullet(master_xml: bytes, colors: ThemeColors) -> BulletStyle | None:
    """Маркер из `p:txStyles/p:bodyStyle/a:lvl1pPr`. `None` — шаблон его не задаёт.

    Явный `buNone` — тоже решение автора, и оно означает список без маркера. Шаблон,
    который молчит, остаётся без маркера по той же причине: придумывать «типовую точку»
    значит дорисовывать чужой дизайн.
    """
    root = etree.fromstring(master_xml)
    body = root.find(f".//{{{P}}}txStyles/{{{P}}}bodyStyle")
    if body is None:
        return None
    lvl1 = body.find(f"{{{A}}}lvl1pPr")
    if lvl1 is None or lvl1.find(f"{{{A}}}buNone") is not None:
        return None

    char_node = lvl1.find(f"{{{A}}}buChar")
    char = (char_node.get("char") or "").strip() if char_node is not None else ""
    if not char:
        return None

    font_node = lvl1.find(f"{{{A}}}buFont")
    font = (font_node.get("typeface") or None) if font_node is not None else None

    return BulletStyle(
        char=char[:4],
        font=font,
        color_ref=_color_ref(lvl1, colors),
        margin_left_emu=max(0, _int_attr(lvl1, "marL")),
        indent_emu=min(0, _int_attr(lvl1, "indent")),
    )


def _int_attr(node: etree._Element, name: str) -> int:
    raw = node.get(name)
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


def _color_ref(lvl1: etree._Element, colors: ThemeColors) -> ColorRef | None:
    """Цвет маркера слотом темы: литерал в IR запрещён (ADR-002).

    Шаблон задаёт цвет и ссылкой (`schemeClr`), и литералом (`srgbClr`). Литерал
    переводится в ближайший слот темы — тем же способом, что и остальные цвета шаблона.
    """
    clr = lvl1.find(f"{{{A}}}buClr")
    if clr is None:
        return None
    scheme = clr.find(f"{{{A}}}schemeClr")
    if scheme is not None:
        value = (scheme.get("val") or "").strip()
        mapped = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}.get(value, value)
        try:
            return ColorRef(mapped)
        except ValueError:
            return None
    srgb = clr.find(f"{{{A}}}srgbClr")
    if srgb is None or not srgb.get("val"):
        return None
    return nearest_color_ref(f"#{srgb.get('val')}", colors)[0]
