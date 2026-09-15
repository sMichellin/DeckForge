"""Разбор темы: `clrScheme` и `fontScheme`. Change (4) `theme-extraction`.

python-pptx не отдаёт тему целиком, поэтому здесь lxml напрямую.

Тема берётся не из `ppt/theme/theme1.xml` «по имени»: в реальных шаблонах тем несколько
(по одной на мастер), и нужная находится по связи мастера. Имя файла ничего не гарантирует.
"""

from __future__ import annotations

from lxml import etree

from deckforge.domain.enums import ColorRef
from deckforge.domain.template import Theme, ThemeColors, ThemeFonts

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"a": A}

#: Порядок обязателен: `clrScheme` в OOXML — последовательность, а не словарь.
SCHEME_SLOTS: tuple[str, ...] = (
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
    "hlink",
    "folHlink",
)


def _resolve_color(slot: etree._Element) -> str | None:
    """Цвет слота схемы в виде `#RRGGBB`.

    Слот может быть задан как `srgbClr` (прямой код) или как `sysClr` — системный цвет
    вроде `windowText`, у которого фактическое значение лежит в атрибуте `lastClr`.
    """
    srgb = slot.find(f"{{{A}}}srgbClr")
    if srgb is not None and srgb.get("val"):
        return f"#{srgb.get('val').upper()}"
    sys_clr = slot.find(f"{{{A}}}sysClr")
    if sys_clr is not None and sys_clr.get("lastClr"):
        return f"#{sys_clr.get('lastClr').upper()}"
    return None


def parse_colors(theme_root: etree._Element) -> ThemeColors:
    """12 цветов схемы. Пустой слот — ошибка парсера, а не повод подставить значение."""
    scheme = theme_root.find(f".//{{{A}}}clrScheme")
    if scheme is None:
        raise ValueError("в теме нет clrScheme")

    found: dict[str, str] = {}
    for slot_name in SCHEME_SLOTS:
        slot = scheme.find(f"{{{A}}}{slot_name}")
        if slot is None:
            continue
        color = _resolve_color(slot)
        if color:
            found[slot_name] = color

    missing = [slot for slot in SCHEME_SLOTS if slot not in found]
    if missing:
        raise ValueError(f"в clrScheme не разобраны слоты: {', '.join(missing)}")
    return ThemeColors.model_validate(found)


def parse_fonts(theme_root: etree._Element) -> ThemeFonts:
    """Мажорная и минорная гарнитуры. `latin` обязателен, `cs` — как есть."""
    scheme = theme_root.find(f".//{{{A}}}fontScheme")
    if scheme is None:
        raise ValueError("в теме нет fontScheme")

    def face(group: str, tag: str) -> str | None:
        node = scheme.find(f"{{{A}}}{group}/{{{A}}}{tag}")
        value = node.get("typeface") if node is not None else None
        return value or None

    major_latin = face("majorFont", "latin")
    minor_latin = face("minorFont", "latin")
    if not major_latin or not minor_latin:
        raise ValueError("в fontScheme не заданы латинские гарнитуры")

    return ThemeFonts(
        major_latin=major_latin,
        minor_latin=minor_latin,
        major_cs=face("majorFont", "cs"),
        minor_cs=face("minorFont", "cs"),
    )


def parse_theme(theme_xml: bytes) -> Theme:
    root = etree.fromstring(theme_xml)
    return Theme(colors=parse_colors(root), fonts=parse_fonts(root))


def nearest_color_ref(hex_color: str, colors: ThemeColors) -> tuple[ColorRef, float]:
    """Ближайший слот темы к произвольному цвету и расстояние до него.

    Нужен там, где шаблон задал цвет литералом в обход темы: чтобы положить в IR ссылку,
    а не `#RRGGBB` (ADR-002).
    """
    from deckforge.domain.rules import delta_e_rgb

    ranked = sorted(
        ((ref, delta_e_rgb(hex_color, colors.get(ref))) for ref in ColorRef),
        key=lambda pair: pair[1],
    )
    return ranked[0]
