"""Маркер списка: макет поверх мастера. Changes (4) `theme-extraction`,
`bullets-from-the-layout` (B11).

Маркер — часть дизайн-системы шаблона: знак, гарнитура, цвет и глубина выноса заданы
автором наравне с палитрой и шкалой. Плейсхолдер их наследует сам, а свободный текстбокс
не наследует ничего, и без этих сведений список выглядит набором абзацев
(прогон 2ac85990b2f2).

Мастером дело не ограничивается. Ни один из трёх шаблонов кейса не объявляет маркер
в `p:txStyles/p:bodyStyle` — знак задан в `lstStyle` плейсхолдера макета, и задан так:
первый уровень отключён, маркер начинается со второго (прогон VK Education `6b1d9e82b612`,
список вышел без маркеров вовсе). Автор шаблона так и пишет: на 55 слайдах-примерах
VK Education 232 абзаца первого уровня идут без знака, а все 21 абзац второго — со знаком.
Первый уровень у этих шаблонов отведён абзацу текста, список живёт со второго.

Отсюда два правила разбора:

* уровень берётся из макета, если макет о нём сказал, иначе из мастера — тот же каскад,
  который применяет PowerPoint;
* список начинается с первого уровня, который шаблон **маркирует**; вместе со знаком он
  получает и вынос этого уровня.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Final

from lxml import etree

from deckforge.domain.enums import ColorRef
from deckforge.domain.template import BulletStyle, ThemeColors
from deckforge.parsing.ooxml.theme import nearest_color_ref

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


#: Глубже третьего уровня не читаем: композитор столько не даёт (правило 7 промпта —
#: не больше шести тезисов), а четвёртый уровень в деловой презентации уже не список.
_LEVELS: Final = 3

#: Просматриваем на уровень глубже: когда первый отключён автором, список сдвигается
#: вниз, и без запаса шаблон потерял бы последнюю ступень вложенности.
_SCAN_LEVELS: Final = _LEVELS + 1


class _Muted:
    """Уровень объявлен без маркера. Это решение автора, а не пробел в шаблоне."""


#: Уровень отключён явно (`buNone`) или объявлен без знака.
MUTED: Final = _Muted()

#: Состояние одного уровня: стиль, отключён, либо `None` — уровень не объявлен вовсе.
_Level = BulletStyle | _Muted | None


def parse_bullets(
    master_xml: bytes,
    colors: ThemeColors,
    layout_xmls: Sequence[bytes] = (),
) -> list[BulletStyle]:
    """Маркеры уровней списка. Пустой список — шаблон не задаёт маркера нигде.

    Явный `buNone` — тоже решение автора, и оно означает список без маркера. Шаблон,
    который молчит, остаётся без маркера по той же причине: придумывать «типовую точку»
    значит дорисовывать чужой дизайн.

    Уровни идут подряд с первого маркированного: как только уровень отключён или
    не объявлен, чтение прекращается. Дырку посередине писатель всё равно заполнил бы
    ближайшим уровнем сверху — пусть это будет одно правило, а не два.
    """
    merged = _merge(_master_levels(master_xml, colors), _layout_levels(layout_xmls, colors))

    levels: list[BulletStyle] = []
    for state in _from_the_first_marked(merged):
        if not isinstance(state, BulletStyle):
            break
        levels.append(state)
    return levels[:_LEVELS]


def parse_bullet(master_xml: bytes, colors: ThemeColors) -> BulletStyle | None:
    """Маркер первого уровня. Остаётся ради вызовов, которым вложенность не нужна."""
    levels = parse_bullets(master_xml, colors)
    return levels[0] if levels else None


def _from_the_first_marked(levels: list[_Level]) -> list[_Level]:
    """Отбрасывает ведущие отключённые уровни: список начинается там, где есть знак."""
    for position, state in enumerate(levels):
        if isinstance(state, BulletStyle):
            return levels[position:]
    return []


def _merge(master: list[_Level], layout: list[_Level]) -> list[_Level]:
    """Каскад по уровням: слово макета весомее слова мастера, молчание — не слово."""
    return [
        theirs if theirs is not None else ours
        for ours, theirs in zip(master, layout, strict=True)
    ]


def _master_levels(master_xml: bytes, colors: ThemeColors) -> list[_Level]:
    root = _root(master_xml)
    body = root.find(f".//{{{P}}}txStyles/{{{P}}}bodyStyle") if root is not None else None
    return _levels_of(body, colors, last_word=True)


def _layout_levels(layout_xmls: Sequence[bytes], colors: ThemeColors) -> list[_Level]:
    """Стиль списка, преобладающий среди тел макетов.

    Голосование, а не первый попавшийся макет: у VK Tech 52 тела из 54 гасят первый
    уровень, а два оставшихся — нет, и по одинокому исключению судить о шаблоне нельзя.
    Макеты без тела (титульные, разделители) в голосовании не участвуют: молчание
    о списке — не мнение о нём.
    """
    votes: Counter[tuple[object, ...]] = Counter()
    seen: dict[tuple[object, ...], list[_Level]] = {}
    for xml in layout_xmls:
        root = _root(xml)
        if root is None:
            continue
        for shape in root.iter(f"{{{P}}}sp"):
            if not _is_body(shape):
                continue
            style = shape.find(f".//{{{P}}}txBody/{{{A}}}lstStyle")
            if style is None:
                continue
            levels = _levels_of(style, colors, last_word=False)
            key = tuple(_key(state) for state in levels)
            votes[key] += 1
            seen.setdefault(key, levels)
    if not votes:
        return [None] * _SCAN_LEVELS
    return seen[votes.most_common(1)[0][0]]


def _is_body(shape: etree._Element) -> bool:
    """Тело слайда: плейсхолдер типа `body` либо без типа — по умолчанию это тело."""
    holder = shape.find(f".//{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
    return holder is not None and (holder.get("type") or "body") == "body"


def _key(state: _Level) -> object:
    if state is None:
        return "—"
    if isinstance(state, BulletStyle):
        return (
            state.char, state.font, state.color_ref,
            state.margin_left_emu, state.indent_emu,
        )
    return "muted"


def _root(xml: bytes) -> etree._Element | None:
    """Нечитаемая часть не валит разбор шаблона: один битый макет — не конец работы."""
    try:
        return etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None


def _levels_of(
    node: etree._Element | None, colors: ThemeColors, *, last_word: bool
) -> list[_Level]:
    if node is None:
        return [None] * _SCAN_LEVELS
    return [
        _level(node.find(f"{{{A}}}lvl{number}pPr"), colors, last_word=last_word)
        for number in range(1, _SCAN_LEVELS + 1)
    ]


def _level(node: etree._Element | None, colors: ThemeColors, *, last_word: bool) -> _Level:
    """Маркер одного уровня. `None` — шаблон о нём промолчал; `MUTED` — сказал «без знака».

    Молчание читается по-разному в зависимости от ступени каскада. Уровень без `buChar`
    в макете — «не переопределяю», знак приедет от мастера: так устроен стандартный
    шаблон python-pptx, где макеты задают отступы, а знак живёт в мастере. Тот же уровень
    в мастере — конец каскада: наследовать больше не от кого, и знака у списка нет
    (VK WorkSpace задаёт гарнитуру маркера, но не сам знак).
    """
    if node is None:
        return None
    if node.find(f"{{{A}}}buNone") is not None:
        return MUTED

    char_node = node.find(f"{{{A}}}buChar")
    char = (char_node.get("char") or "").strip() if char_node is not None else ""
    if not char:
        return MUTED if last_word else None

    font_node = node.find(f"{{{A}}}buFont")
    font = (font_node.get("typeface") or None) if font_node is not None else None

    return BulletStyle(
        char=char[:4],
        font=font,
        color_ref=_color_ref(node, colors),
        margin_left_emu=max(0, _int_attr(node, "marL")),
        indent_emu=min(0, _int_attr(node, "indent")),
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
