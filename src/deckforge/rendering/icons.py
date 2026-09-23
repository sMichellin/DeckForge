"""Иконки Lucide (ISC): SVG → нативная геометрия с цветом темы. Change (21) `smartart-icons`.

Иконка вставляется не картинкой, а фигурой с `a:custGeom`: пути SVG переведены в отрезки
и кривые Безье DrawingML. Так она векторная, редактируется в PowerPoint и красится ссылкой
на цвет темы (ADR-002) — SVG-картинка несла бы цвет литералом. Растр не используется (C3).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache

from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Emu

from deckforge.config import ASSETS_DIR
from deckforge.domain.enums import ColorRef
from deckforge.domain.slide import IconBlock
from deckforge.rendering.theme_binding import apply_theme_color

LUCIDE_NODES = ASSETS_DIR / "icons" / "lucide" / "icon-nodes.json"
#: Сетка Lucide — 24 × 24, линия — 2 единицы сетки. Это формат библиотеки, а не шаблона.
ICON_VIEWBOX = 24
ICON_STROKE_WIDTH = 2
#: Единиц пути DrawingML на единицу сетки: координаты Lucide даны с точностью до сотых.
_PATH_SCALE = 100

IconNode = tuple[str, dict[str, str]]


# --- сегменты -----------------------------------------------------------------------


@dataclass(frozen=True)
class Move:
    x: float
    y: float


@dataclass(frozen=True)
class Line:
    x: float
    y: float


@dataclass(frozen=True)
class Cubic:
    x1: float
    y1: float
    x2: float
    y2: float
    x: float
    y: float


@dataclass(frozen=True)
class Close:
    pass


Segment = Move | Line | Cubic | Close


# --- библиотека ---------------------------------------------------------------------


@lru_cache(maxsize=1)
def _library() -> dict[str, list[IconNode]]:
    raw = json.loads(LUCIDE_NODES.read_text(encoding="utf-8"))
    return {name: [(tag, dict(attrs)) for tag, attrs in nodes] for name, nodes in raw.items()}


def icon_names() -> list[str]:
    return sorted(_library())


@lru_cache(maxsize=1)
def _compact_names() -> dict[str, str]:
    """Имя без дефисов → имя Lucide. Совпадений у разных иконок нет (проверено тестом)."""
    return {name.replace("-", ""): name for name in _library()}


def icon_name(query: str) -> str | None:
    """Имя Lucide для `shield-check`, `ShieldCheck`, `shield_check`, `Clock3`, `Grid2x2`.

    Сначала точное имя, потом без дефисов: разбить `Grid2x2` на слова правилом нельзя
    (`grid-2x2`, а не `grid-2x-2`), а сравнить без разделителей — можно.
    """
    name = re.sub(r"[\s_]+", "-", query.strip()).lower()
    if name in _library():
        return name
    return _compact_names().get(name.replace("-", ""))


def icon_nodes(query: str) -> list[IconNode] | None:
    """Элементы SVG иконки или `None`, если такой иконки в Lucide нет."""
    name = icon_name(query)
    return _library()[name] if name is not None else None


# --- разбор SVG ---------------------------------------------------------------------

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_SEPARATORS = " \t\r\n,"


class _Reader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in _SEPARATORS:
            self.pos += 1

    def done(self) -> bool:
        self.skip()
        return self.pos >= len(self.text)

    def letter(self) -> str | None:
        self.skip()
        if self.pos < len(self.text) and self.text[self.pos].isalpha():
            self.pos += 1
            return self.text[self.pos - 1]
        return None

    def number(self) -> float:
        self.skip()
        match = _NUMBER.match(self.text, self.pos)
        if match is None:
            raise ValueError(f"в пути SVG ждали число: {self.text[self.pos:self.pos + 20]!r}")
        self.pos = match.end()
        return float(match.group())

    def flag(self) -> bool:
        """Флаги дуги — одна цифра, и за ней число может идти без разделителя: `a1 1 0 011 1`."""
        self.skip()
        char = self.text[self.pos:self.pos + 1]
        if char not in ("0", "1"):
            raise ValueError(f"в пути SVG ждали флаг дуги: {self.text[self.pos:self.pos + 20]!r}")
        self.pos += 1
        return char == "1"


def path_segments(d: str) -> list[Segment]:
    """Путь SVG → абсолютные `Move`/`Line`/`Cubic`/`Close`; дуги и квадратичные — в кубические."""
    reader = _Reader(d)
    out: list[Segment] = []
    x = y = start_x = start_y = 0.0
    command: str | None = None
    closed = False
    #: Вторая управляющая точка последней кубической и управляющая последней квадратичной —
    #: для гладких `S` и `T`.
    cubic_control: tuple[float, float] | None = None
    quad_control: tuple[float, float] | None = None

    while not reader.done():
        command = reader.letter() or command
        if command is None:
            raise ValueError(f"путь SVG начинается не с команды: {d[:20]!r}")
        kind, relative = command.upper(), command.islower()
        if closed and kind != "M":
            # SVG продолжает от начала закрытого контура, а в DrawingML после `close`
            # текущей точки нет: без `moveTo` PowerPoint теряет штрих.
            out.append(Move(x, y))
        closed = kind == "Z"
        dx, dy = (x, y) if relative else (0.0, 0.0)
        next_cubic: tuple[float, float] | None = None
        next_quad: tuple[float, float] | None = None

        if kind == "Z":
            out.append(Close())
            x, y = start_x, start_y
            command = None
        elif kind == "M":
            x, y = dx + reader.number(), dy + reader.number()
            start_x, start_y = x, y
            out.append(Move(x, y))
            # Пары координат после `M` — это `L`.
            command = "l" if relative else "L"
        elif kind == "L":
            x, y = dx + reader.number(), dy + reader.number()
            out.append(Line(x, y))
        elif kind == "H":
            x = dx + reader.number()
            out.append(Line(x, y))
        elif kind == "V":
            y = dy + reader.number()
            out.append(Line(x, y))
        elif kind in ("C", "S"):
            if kind == "C":
                x1, y1 = dx + reader.number(), dy + reader.number()
            else:
                x1, y1 = _reflect(cubic_control, x, y)
            x2, y2 = dx + reader.number(), dy + reader.number()
            x, y = dx + reader.number(), dy + reader.number()
            out.append(Cubic(x1, y1, x2, y2, x, y))
            next_cubic = (x2, y2)
        elif kind in ("Q", "T"):
            if kind == "Q":
                qx, qy = dx + reader.number(), dy + reader.number()
            else:
                qx, qy = _reflect(quad_control, x, y)
            end_x, end_y = dx + reader.number(), dy + reader.number()
            out.append(Cubic(x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                             end_x + 2 / 3 * (qx - end_x), end_y + 2 / 3 * (qy - end_y),
                             end_x, end_y))
            x, y = end_x, end_y
            next_quad = (qx, qy)
        elif kind == "A":
            rx, ry, rotation = reader.number(), reader.number(), reader.number()
            large, sweep = reader.flag(), reader.flag()
            end_x, end_y = dx + reader.number(), dy + reader.number()
            out += _arc(x, y, rx, ry, rotation, large, sweep, end_x, end_y)
            x, y = end_x, end_y
        else:
            raise ValueError(f"команда пути SVG {command!r} не поддерживается")
        cubic_control, quad_control = next_cubic, next_quad
    return out


def _reflect(control: tuple[float, float] | None, x: float, y: float) -> tuple[float, float]:
    return (2 * x - control[0], 2 * y - control[1]) if control else (x, y)


def _arc(
    x1: float, y1: float, rx: float, ry: float, rotation: float,
    large: bool, sweep: bool, x2: float, y2: float,
) -> list[Segment]:
    """Дуга SVG (конечные точки) → кубические, не больше четверти эллипса на кривую.

    Переход к центру эллипса — по приложению F.6.5 спецификации SVG 1.1.
    """
    if (x1, y1) == (x2, y2):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [Line(x2, y2)]
    phi = math.radians(rotation)
    cos, sin = math.cos(phi), math.sin(phi)
    hx, hy = (x1 - x2) / 2, (y1 - y2) / 2
    px, py = cos * hx + sin * hy, -sin * hx + cos * hy
    scale = px**2 / rx**2 + py**2 / ry**2
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    numerator = rx**2 * ry**2 - rx**2 * py**2 - ry**2 * px**2
    denominator = rx**2 * py**2 + ry**2 * px**2
    coef = math.sqrt(max(0.0, numerator / denominator))
    if large == sweep:
        coef = -coef
    cpx, cpy = coef * rx * py / ry, -coef * ry * px / rx
    cx = cos * cpx - sin * cpy + (x1 + x2) / 2
    cy = sin * cpx + cos * cpy + (y1 + y2) / 2

    ux, uy = (px - cpx) / rx, (py - cpy) / ry
    vx, vy = (-px - cpx) / rx, (-py - cpy) / ry
    theta = math.atan2(uy, ux)
    delta = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi

    def point(t: float) -> tuple[float, float]:
        return (cx + rx * math.cos(t) * cos - ry * math.sin(t) * sin,
                cy + rx * math.cos(t) * sin + ry * math.sin(t) * cos)

    def tangent(t: float) -> tuple[float, float]:
        return (-rx * math.sin(t) * cos - ry * math.cos(t) * sin,
                -rx * math.sin(t) * sin + ry * math.cos(t) * cos)

    pieces = max(1, math.ceil(abs(delta) / (math.pi / 2) - 1e-9))
    step = delta / pieces
    k = 4 / 3 * math.tan(step / 4)
    out: list[Segment] = []
    for i in range(pieces):
        t1, t2 = theta + i * step, theta + (i + 1) * step
        (ax, ay), (bx, by) = point(t1), point(t2)
        (tx1, ty1), (tx2, ty2) = tangent(t1), tangent(t2)
        if i == pieces - 1:
            bx, by = x2, y2
        out.append(Cubic(ax + k * tx1, ay + k * ty1, bx - k * tx2, by - k * ty2, bx, by))
    return out


def _num(attrs: dict[str, str], key: str, default: float = 0.0) -> float:
    value = attrs.get(key)
    return float(value) if value is not None else default


def node_segments(tag: str, attrs: dict[str, str]) -> list[Segment]:
    """Элемент SVG иконки → сегменты. Поддержаны все элементы, что встречаются в Lucide."""
    if tag == "path":
        return path_segments(attrs["d"])
    if tag in ("circle", "ellipse"):
        cx, cy = _num(attrs, "cx"), _num(attrs, "cy")
        rx = _num(attrs, "r") if tag == "circle" else _num(attrs, "rx")
        ry = _num(attrs, "r") if tag == "circle" else _num(attrs, "ry")
        return [
            Move(cx + rx, cy),
            *_arc(cx + rx, cy, rx, ry, 0, False, True, cx - rx, cy),
            *_arc(cx - rx, cy, rx, ry, 0, False, True, cx + rx, cy),
            Close(),
        ]
    if tag == "rect":
        x, y = _num(attrs, "x"), _num(attrs, "y")
        w, h = _num(attrs, "width"), _num(attrs, "height")
        # Если задан один радиус, второй равен ему (SVG 1.1, 10.2).
        rx = _num(attrs, "rx", _num(attrs, "ry"))
        ry = _num(attrs, "ry", rx)
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx == 0 or ry == 0:
            return [Move(x, y), Line(x + w, y), Line(x + w, y + h), Line(x, y + h), Close()]
        return [
            Move(x + rx, y), Line(x + w - rx, y),
            *_arc(x + w - rx, y, rx, ry, 0, False, True, x + w, y + ry),
            Line(x + w, y + h - ry),
            *_arc(x + w, y + h - ry, rx, ry, 0, False, True, x + w - rx, y + h),
            Line(x + rx, y + h),
            *_arc(x + rx, y + h, rx, ry, 0, False, True, x, y + h - ry),
            Line(x, y + ry),
            *_arc(x, y + ry, rx, ry, 0, False, True, x + rx, y),
            Close(),
        ]
    if tag == "line":
        return [Move(_num(attrs, "x1"), _num(attrs, "y1")),
                Line(_num(attrs, "x2"), _num(attrs, "y2"))]
    if tag in ("polyline", "polygon"):
        values = [float(v) for v in _NUMBER.findall(attrs["points"])]
        points = list(zip(values[::2], values[1::2], strict=False))
        out: list[Segment] = [Move(*points[0]), *(Line(px, py) for px, py in points[1:])]
        return [*out, Close()] if tag == "polygon" else out
    raise ValueError(f"элемент SVG {tag!r} не поддерживается")


# --- запись -------------------------------------------------------------------------


def _pt(x: float, y: float) -> str:
    return f'<a:pt x="{round(x * _PATH_SCALE)}" y="{round(y * _PATH_SCALE)}"/>'


def _path_xml(segments: list[Segment], filled: bool) -> str:
    size = ICON_VIEWBOX * _PATH_SCALE
    body = []
    for s in segments:
        if isinstance(s, Move):
            body.append(f"<a:moveTo>{_pt(s.x, s.y)}</a:moveTo>")
        elif isinstance(s, Line):
            body.append(f"<a:lnTo>{_pt(s.x, s.y)}</a:lnTo>")
        elif isinstance(s, Cubic):
            body.append(
                f"<a:cubicBezTo>{_pt(s.x1, s.y1)}{_pt(s.x2, s.y2)}{_pt(s.x, s.y)}</a:cubicBezTo>"
            )
        else:
            body.append("<a:close/>")
    fill = "" if filled else ' fill="none"'
    return f'<a:path w="{size}" h="{size}"{fill}>{"".join(body)}</a:path>'


def add_icon(slide: object, block: IconBlock, default: ColorRef = ColorRef.ACCENT1) -> object:
    """Квадратная иконка по центру рамки блока, линия и заливка — ссылкой на цвет темы.

    `default` — цвет, когда IR его не назвал: акцент по роли дизайн-системы (DG3)."""
    nodes = icon_nodes(block.query)
    if nodes is None:
        raise KeyError(f"иконки {block.query} нет в Lucide")
    box = block.bbox
    if box is None:
        raise ValueError(f"иконка {block.block_id} без координат")
    side = min(box.cx, box.cy)
    shape = slide.shapes.add_shape(  # type: ignore[attr-defined]
        MSO_SHAPE.RECTANGLE,
        Emu(box.x + (box.cx - side) // 2), Emu(box.y + (box.cy - side) // 2), Emu(side), Emu(side),
    )
    shape.name = f"Иконка {icon_name(block.query)}"
    element = shape._element
    # Стиль автофигуры ссылается на эффекты темы — у иконки их быть не должно.
    style = element.find(qn("p:style"))
    if style is not None:
        element.remove(style)

    filled = [attrs.get("fill", "none") != "none" for _, attrs in nodes]
    paths = "".join(
        _path_xml(node_segments(tag, attrs), fill)
        for (tag, attrs), fill in zip(nodes, filled, strict=True)
    )
    geometry = parse_xml(
        f"<a:custGeom {nsdecls('a')}><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>"
        f'<a:rect l="0" t="0" r="r" b="b"/><a:pathLst>{paths}</a:pathLst></a:custGeom>'
    )
    preset = element.spPr.find(qn("a:prstGeom"))
    preset.addprevious(geometry)
    element.spPr.remove(preset)

    color = block.color_ref or default
    if any(filled):
        apply_theme_color(shape.fill, color)
    else:
        shape.fill.background()
    apply_theme_color(shape.line, color)
    shape.line.width = Emu(round(side * ICON_STROKE_WIDTH / ICON_VIEWBOX))
    line = element.spPr.find(qn("a:ln"))
    line.set("cap", "rnd")
    line.append(parse_xml(f"<a:round {nsdecls('a')}/>"))
    return shape
