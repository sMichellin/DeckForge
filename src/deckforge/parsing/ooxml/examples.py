"""Слайды-примеры шаблона → `TemplateExample`. Change `design-system-from-examples` (DS1).

Манифест называется дизайн-системой шаблона (ADR-003), но собирался из мастера и макетов,
а слайды шаблона парсер не открывал вовсе. Между тем именно там дизайн-система и живёт:
у трёх шаблонов кейса от 87 % до 96 % содержимого примеров лежит **вне** плейсхолдеров —
обычными фигурами поверх почти пустого макета. Классификатору по плейсхолдерам на таком
шаблоне нечего классифицировать (B4), а выбору макета — не с чем сверяться (B8, DS5).

Разбор детерминированный: модель здесь не участвует. Разбор шаблона и так занимал
до сорока минут (D1), и добавлять к нему вызовы VLM нельзя.

Группы раскрываются с пересчётом: группа задаёт детям свою систему координат
(`chOff`/`chExt`) и растягивает её до собственной рамки (`off`/`ext`), поэтому иначе
и геометрия, и кегль внутри неё оказались бы в чужом масштабе.

Оговорка к заданию DS2: странные кегли VK Tech — 6,75 и 8,12 pt — **не** от групп.
Групп в этом шаблоне всего шесть, а такие кегли встречаются 80 и 131 раз. Дело в размере
слайда: у VK Tech он 10 × 5,62″ против 13,33 × 7,5″ у двух других, и вся типографика
в нём мельче ровно в 1,33 раза. Кегли здесь остаются такими, какие в файле: внутри
одного шаблона они сравнимы между собой, а приводить их к общему масштабу нужно только
при сравнении шаблонов — это делает `scripts/bench_design_system.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from lxml import etree

from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import (
    ExampleShape,
    LayoutSpec,
    ShapeKind,
    TemplateExample,
    Theme,
)
from deckforge.parsing.ooxml.theme import nearest_color_ref

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"

#: Ссылки на гарнитуры темы: в тексте примера вместо имени часто стоит ссылка.
_FONT_REFS = {
    "+mj-lt": "major_latin",
    "+mn-lt": "minor_latin",
    "+mj-cs": "major_cs",
    "+mn-cs": "minor_cs",
}

#: Литеральный цвет ближе этого расстояния к слоту темы — это и есть слот.
#: Порог тот же, что принят для палитры в `design-system-from-examples`.
_SAME_COLOR_DELTA_E = 2.3


@dataclass(frozen=True, slots=True)
class _Frame:
    """Перевод координат ребёнка группы в координаты слайда."""

    dx: int = 0
    dy: int = 0
    sx: float = 1.0
    sy: float = 1.0

    def point(self, x: int, y: int) -> tuple[int, int]:
        return round(self.dx + x * self.sx), round(self.dy + y * self.sy)

    def size(self, cx: int, cy: int) -> tuple[int, int]:
        return max(1, round(cx * self.sx)), max(1, round(cy * self.sy))

    @property
    def font_scale(self) -> float:
        """Кегль масштабируется группой так же, как её содержимое целиком."""
        return sqrt(abs(self.sx * self.sy)) or 1.0

    def nested(self, group: etree._Element) -> _Frame:
        """Рамка внутри группы: её дети живут в системе координат `chOff`/`chExt`."""
        xfrm = group.find(f"{{{P}}}grpSpPr/{{{A}}}xfrm")
        if xfrm is None:
            return self
        off, ext = xfrm.find(f"{{{A}}}off"), xfrm.find(f"{{{A}}}ext")
        ch_off, ch_ext = xfrm.find(f"{{{A}}}chOff"), xfrm.find(f"{{{A}}}chExt")
        if off is None or ext is None or ch_ext is None:
            return self
        child_cx, child_cy = _int(ch_ext, "cx"), _int(ch_ext, "cy")
        if not child_cx or not child_cy:
            return self
        sx = _int(ext, "cx") / child_cx
        sy = _int(ext, "cy") / child_cy
        origin_x, origin_y = self.point(_int(off, "x"), _int(off, "y"))
        child_x = _int(ch_off, "x") if ch_off is not None else 0
        child_y = _int(ch_off, "y") if ch_off is not None else 0
        return _Frame(
            dx=round(origin_x - child_x * sx * self.sx),
            dy=round(origin_y - child_y * sy * self.sy),
            sx=sx * self.sx,
            sy=sy * self.sy,
        )


def parse_example(
    slide_index: int,
    slide_xml: bytes,
    layout: LayoutSpec | None,
    theme: Theme,
) -> TemplateExample:
    """Один слайд-пример: фигуры в координатах слайда, группы раскрыты.

    Фигура без собственной геометрии пропускается: рамку она наследует от плейсхолдера
    макета, и для замера дизайн-системы такая запись ничего не говорит.
    """
    try:
        root = etree.fromstring(slide_xml)
    except etree.XMLSyntaxError:
        return TemplateExample(slide_index=slide_index, layout_id=None)

    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree")
    shapes: list[ExampleShape] = []
    if tree is not None:
        _collect(tree, _Frame(), layout, theme, shapes)
    return TemplateExample(
        slide_index=slide_index,
        layout_id=layout.layout_id if layout is not None else None,
        shapes=shapes,
    )


def _collect(
    parent: etree._Element,
    frame: _Frame,
    layout: LayoutSpec | None,
    theme: Theme,
    out: list[ExampleShape],
) -> None:
    for node in parent:
        tag = etree.QName(node).localname
        if tag == "grpSp":
            _collect(node, frame.nested(node), layout, theme, out)
            continue
        if tag not in {"sp", "pic", "graphicFrame", "cxnSp"}:
            continue
        shape = _shape(node, tag, frame, layout, theme, len(out))
        if shape is not None:
            out.append(shape)


def _shape(
    node: etree._Element,
    tag: str,
    frame: _Frame,
    layout: LayoutSpec | None,
    theme: Theme,
    z: int,
) -> ExampleShape | None:
    box = _geometry(node, frame)
    if box is None:
        return None
    x, y, cx, cy = box
    text = _text_of(node)
    idx = _placeholder_idx(node)
    size_pt = _size_pt(node, frame)
    text_ref, text_hex = _text_colour(node, theme)
    fill_ref, fill_hex = _fill_colour(node, theme)
    return ExampleShape(
        shape_id=f"s{z:03d}",
        kind=_kind(node, tag, text),
        x=x,
        y=y,
        cx=cx,
        cy=cy,
        z=z,
        placeholder_idx=idx,
        role=_role(idx, layout),
        text_len=len(text),
        size_pt=size_pt,
        font_family=_font(node, theme),
        color_ref=text_ref,
        color_hex=text_hex,
        fill_ref=fill_ref,
        fill_hex=fill_hex,
    )


def _geometry(node: etree._Element, frame: _Frame) -> tuple[int, int, int, int] | None:
    xfrm = node.find(f".//{{{A}}}xfrm")
    if xfrm is None:
        return None
    off, ext = xfrm.find(f"{{{A}}}off"), xfrm.find(f"{{{A}}}ext")
    if off is None or ext is None:
        return None
    cx, cy = _int(ext, "cx"), _int(ext, "cy")
    if cx <= 0 or cy <= 0:
        return None
    x, y = frame.point(_int(off, "x"), _int(off, "y"))
    width, height = frame.size(cx, cy)
    return x, y, width, height


def _kind(node: etree._Element, tag: str, text: str) -> ShapeKind:
    if tag == "pic":
        return ShapeKind.PICTURE
    if tag == "graphicFrame":
        if node.find(f".//{{{A}}}tbl") is not None:
            return ShapeKind.TABLE
        uri = node.find(f".//{{{A}}}graphicData")
        if uri is not None and "chart" in (uri.get("uri") or ""):
            return ShapeKind.CHART
        return ShapeKind.SHAPE
    return ShapeKind.TEXT if text else ShapeKind.SHAPE


def _text_of(node: etree._Element) -> str:
    return "".join(run.text or "" for run in node.iter(f"{{{A}}}t")).strip()


def _placeholder_idx(node: etree._Element) -> int | None:
    holder = node.find(f".//{{{P}}}nvPr/{{{P}}}ph")
    if holder is None:
        return None
    raw = holder.get("idx")
    if raw is None:
        # Заголовок объявляют без idx: у него он нулевой по умолчанию.
        return 0
    try:
        return int(raw)
    except ValueError:
        return None


def _role(idx: int | None, layout: LayoutSpec | None) -> TextRole | None:
    """Роль берётся у плейсхолдера макета: у свободной фигуры её назвать нечем.

    Судить о роли по кеглю можно только вместе со шкалой, а шкала сама выводится из
    этих же наблюдений — вышла бы ссылка на себя. Свободные фигуры роль получат в DS3,
    где будут разбираться компоненты.
    """
    if idx is None or layout is None:
        return None
    placeholder = layout.placeholder(idx)
    return placeholder.role if placeholder is not None else None


def _size_pt(node: etree._Element, frame: _Frame) -> float | None:
    """Наибольший кегль фигуры, приведённый к масштабу слайда."""
    sizes = [
        _int(props, "sz")
        for props in node.iter(f"{{{A}}}rPr")
        if props.get("sz") is not None
    ]
    if not sizes:
        return None
    biggest = max(sizes) / 100 * frame.font_scale
    return round(biggest, 2) if biggest > 0 else None


def _font(node: etree._Element, theme: Theme) -> str | None:
    for latin in node.iter(f"{{{A}}}latin"):
        typeface = (latin.get("typeface") or "").strip()
        if not typeface:
            continue
        slot = _FONT_REFS.get(typeface)
        if slot is None:
            return typeface
        resolved = getattr(theme.fonts, slot, None)
        if resolved:
            return str(resolved)
    return None


def _text_colour(node: etree._Element, theme: Theme) -> tuple[ColorRef | None, str | None]:
    """Цвет букв: первый явно заданный в свойствах текста."""
    for props in node.iter(f"{{{A}}}rPr"):
        found = _solid_fill(props, theme)
        if found != (None, None):
            return found
    return None, None


def _fill_colour(node: etree._Element, theme: Theme) -> tuple[ColorRef | None, str | None]:
    """Заливка самой фигуры. Из неё складывается палитра: серые и акценты шаблона
    живут именно в заливках карточек и плашек, а не в цвете букв."""
    props = node.find(f"{{{P}}}spPr")
    return _solid_fill(props, theme) if props is not None else (None, None)


def _solid_fill(
    props: etree._Element, theme: Theme
) -> tuple[ColorRef | None, str | None]:
    """Слот темы, если он назван или литерал к нему сводится; иначе литерал как есть."""
    fill = props.find(f"{{{A}}}solidFill")
    if fill is None:
        return None, None
    scheme = fill.find(f"{{{A}}}schemeClr")
    if scheme is not None:
        value = (scheme.get("val") or "").strip()
        mapped = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}.get(value, value)
        try:
            return ColorRef(mapped), None
        except ValueError:
            return None, None
    srgb = fill.find(f"{{{A}}}srgbClr")
    if srgb is not None and srgb.get("val"):
        literal = f"#{srgb.get('val')}".upper()
        ref, delta = nearest_color_ref(literal, theme.colors)
        return (ref, None) if delta < _SAME_COLOR_DELTA_E else (ref, literal)
    return None, None


def _int(node: etree._Element, name: str) -> int:
    raw = node.get(name)
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0
