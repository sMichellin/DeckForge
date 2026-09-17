"""Экспорт .html из `DeckIR`. Change (22) `export-html`.

Собирается из IR, а не конвертацией pptx: так html наследует те же цвета и типошкалу темы,
а объекты остаются текстом и векторами (C3, C4).

Цвета темы — CSS-переменные в одном блоке `:root`; в разметке только `var(--…)`, поэтому смена
шаблона меняет один этот блок. Блоки ставятся абсолютно в процентах от слайда, кегли —
в `cqw` от ширины слайда: пропорции сохраняются при любой ширине окна.

Файла шаблона html не видит (ADR-003): фон и декор макета в манифесте не лежат, поэтому
передаётся дизайн-система — палитра, гарнитуры, кегли и места блоков, — но не картинки макета.
"""

from __future__ import annotations

import base64
import math
import mimetypes
from collections.abc import Callable
from html import escape
from pathlib import Path

from deckforge.domain.base import BBox
from deckforge.domain.content import ContentPackage, Dataset
from deckforge.domain.enums import ChartType, ColorRef, ImageFit, TextRole
from deckforge.domain.rules import contrast_ratio
from deckforge.domain.slide import (
    Block,
    BulletsBlock,
    ChartBlock,
    DeckIR,
    ImageBlock,
    KpiBlock,
    SlideIR,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import TemplateManifest, TypographyStep
from deckforge.domain.units import EMU_PER_PT, TEXT_FRAME_INSET_X_EMU, TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.metrics import LINE_HEIGHT_RATIO
from deckforge.layout.tabular import format_number, table_cells, table_has_header
from deckforge.rendering.writer import SlideDegrader, SlideValidator, WriterError

_ACCENTS = [
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
]
_ROUND = frozenset({ChartType.PIE, ChartType.DOUGHNUT})
_HORIZONTAL = frozenset({ChartType.CLUSTERED_BAR, ChartType.STACKED_BAR})
_STACKED = frozenset({ChartType.STACKED_BAR, ChartType.STACKED_COLUMN})
_LINES = frozenset({ChartType.LINE, ChartType.LINE_MARKERS, ChartType.AREA})

#: Ширина SVG диаграммы в собственных единицах; высота — по пропорциям рамки.
_SVG_WIDTH = 1000
#: Доли рамки диаграммы под подписи осей и легенду — вёрстка SVG, а не свойство шаблона.
_PLOT_LEFT, _PLOT_RIGHT, _PLOT_TOP, _PLOT_BOTTOM = 0.1, 0.03, 0.06, 0.2
_BAR_GROUP_SHARE = 0.7
_DOUGHNUT_HOLE = 0.55
#: Ниже этого контраста цвет на фоне практически не виден (белый на белом — 1,0, светло-серый
#: на белом — около 1,1). Это порог невидимости, а не доступности: норма WCAG для графики (3:1)
#: отбросила бы обычные фирменные акценты — зелёный и оранжевый на белом бывают ниже 3:1.
_INVISIBLE_CONTRAST = 1.5
#: Толщина линии и радиусы точек в единицах SVG (ширина диаграммы — `_SVG_WIDTH`).
_LINE_WIDTH, _MARKER_RADIUS, _POINT_RADIUS = 3, 6, 7

Position = Callable[[float], float]


def _var(ref: ColorRef | None) -> str:
    return f"var(--{(ref or ColorRef.DK1).value})"


def _pct(value: int, total: int) -> str:
    return f"{value / total * 100:.4f}%"


class _HtmlDeck:
    def __init__(self, manifest: TemplateManifest, content: ContentPackage | None) -> None:
        self.manifest = manifest
        self.content = content
        self.cx = manifest.slide_size.cx_emu
        self.cy = manifest.slide_size.cy_emu

    # --- единицы ----------------------------------------------------------------

    def cqw(self, emu: float) -> str:
        return f"{emu / self.cx * 100:.4f}cqw"

    def font_size(self, size_pt: float) -> str:
        return self.cqw(size_pt * EMU_PER_PT)

    def step(self, role: TextRole) -> TypographyStep | None:
        return self.manifest.typography(role) or self.manifest.typography(TextRole.BODY)

    def family(self, step: TypographyStep | None) -> str:
        fonts = self.manifest.theme.fonts
        name = (fonts.get(step.font_ref) if step else None) or fonts.minor_latin
        return f"'{escape(name, quote=True)}', sans-serif"

    def place(self, box: BBox) -> str:
        return (
            f"left: {_pct(box.x, self.cx)}; top: {_pct(box.y, self.cy)}; "
            f"width: {_pct(box.cx, self.cx)}; height: {_pct(box.cy, self.cy)}"
        )

    # --- документ ---------------------------------------------------------------

    def document(self, deck: DeckIR) -> str:
        colors = "".join(
            f"--{ref.value}: {self.manifest.theme.colors.get(ref)}; " for ref in ColorRef
        )
        body = "\n".join(self.slide(slide, i) for i, slide in enumerate(deck.slides, 1))
        return (
            f'<!doctype html>\n<html lang="{escape(deck.language, quote=True)}">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{escape(deck.deck_id)}</title>\n<style>\n"
            f":root {{ {colors}}}\n{self.css()}\n</style>\n</head>\n"
            f"<body>\n{body}\n</body>\n</html>\n"
        )

    def css(self) -> str:
        body = self.step(TextRole.BODY)
        return f"""
body {{ margin: 0; padding: 2vh 0; background: var(--dk2); font-family: {self.family(body)}; }}
.slide {{ position: relative; width: min(96vw, calc(94vh * {self.cx} / {self.cy}));
  aspect-ratio: {self.cx} / {self.cy}; margin: 0 auto 2vh; overflow: hidden;
  background: var(--lt1); container-type: inline-size; break-after: page; }}
.block {{ position: absolute; box-sizing: border-box; overflow: hidden;
  padding: {self.cqw(TEXT_FRAME_INSET_Y_EMU)} {self.cqw(TEXT_FRAME_INSET_X_EMU)};
  line-height: {LINE_HEIGHT_RATIO}; overflow-wrap: anywhere; }}
.block p {{ margin: 0; white-space: pre-wrap; }}
.block ul {{ margin: 0; padding: 0; list-style: none; }}
.block li::before {{ content: "•"; display: inline-block; width: 1em; margin-left: -1em; }}
.level-0 {{ padding-left: 1em; }} .level-1 {{ padding-left: 2em; }}
.level-2 {{ padding-left: 3em; }}
.level-3 {{ padding-left: 4em; }} .level-4 {{ padding-left: 5em; }}
.block table {{ width: 100%; border-collapse: collapse; }}
.block th {{ text-align: left; background: var(--accent1); color: var(--lt1); }}
.block td, .block th {{
  padding: {self.cqw(TEXT_FRAME_INSET_Y_EMU)} {self.cqw(TEXT_FRAME_INSET_X_EMU)};
  border-bottom: 1px solid var(--lt2); }}
.banded tbody tr:nth-child(even) {{ background: var(--lt2); }}
.kpi-row {{ display: flex; width: 100%; }} .kpi-row > div {{ flex: 1; }}
.block img {{ width: 100%; height: 100%; display: block; }}
.block svg {{ width: 100%; height: 100%; display: block; overflow: visible; }}
.image {{ padding: 0; }}
@media print {{ body {{ background: none; padding: 0; }} .slide {{ margin: 0; width: 100vw; }} }}
"""

    def slide(self, slide: SlideIR, number: int) -> str:
        layout = self.manifest.layout(slide.layout_id)
        blocks = "".join(self.block(slide, block, layout) for block in slide.blocks)
        notes = (
            f'<aside class="notes" hidden>{escape(slide.speaker_note)}</aside>'
            if slide.speaker_note
            else ""
        )
        return (
            f'<section class="slide" id="{escape(slide.slide_id, quote=True)}" '
            f'aria-label="Слайд {number}">{blocks}{notes}</section>'
        )

    def block(self, slide: SlideIR, block: Block, layout: object) -> str:
        box = block.bbox
        if box is None and isinstance(block, TextBlock | BulletsBlock):
            placeholder = layout.placeholder(block.placeholder_idx)  # type: ignore[attr-defined]
            box = placeholder.bbox
        if box is None:
            return ""
        size = (
            slide.fit_report[block.block_id].final_size_pt
            if block.block_id in (slide.fit_report)
            else None
        )
        head = f'data-block="{escape(block.block_id, quote=True)}"'

        if isinstance(block, TextBlock | BulletsBlock):
            step = self.step(block.role)
            color = (block.color_ref if isinstance(block, TextBlock) else None) or (
                step.color_ref if step else None
            )
            style = (
                f"{self.place(box)}; font-size: {self.font_size(size or 0)}; "
                f"color: {_var(color)}; font-family: {self.family(step)}"
                + ("; font-weight: bold" if step and step.bold else "")
            )
            if isinstance(block, TextBlock):
                paragraphs = "".join(f"<p>{escape(p)}</p>" for p in block.text.split("\n"))
                return f'<div class="block text" {head} style="{style}">{paragraphs}</div>'
            items = "".join(
                f'<li class="level-{item.level}">{escape(item.text)}</li>' for item in block.items
            )
            return f'<div class="block bullets" {head} style="{style}"><ul>{items}</ul></div>'

        if isinstance(block, ImageBlock):
            image = self.image(block)
            return f'<div class="block image" {head} style="{self.place(box)}">{image}</div>'
        if isinstance(block, TableBlock):
            return (
                f'<div class="block table" {head} style="{self.place(box)}; '
                f'font-size: {self.font_size(size or 0)}">{self.table(block)}</div>'
            )
        if isinstance(block, KpiBlock):
            return (
                f'<div class="block kpi" {head} style="{self.place(box)}">'
                f"{self.kpi(block, size or 0)}</div>"
            )
        if isinstance(block, ChartBlock):
            dataset = self.dataset(block.dataset_ref)
            svg = self.chart(block, dataset, box) if dataset is not None else ""
            return f'<div class="block chart" {head} style="{self.place(box)}">{svg}</div>'
        return ""

    # --- объекты ----------------------------------------------------------------

    def visible(self, refs: list[ColorRef]) -> list[ColorRef]:
        """Цвета, различимые на фоне html-слайда (`lt1`).

        В pptx фон задаёт макет, и белый акцент на тёмном макете виден; в html фона макета нет,
        и та же серия пропала бы. Если различимых нет вовсе, берутся все — пустая диаграмма хуже.
        """
        colors = self.manifest.theme.colors
        background = colors.get(ColorRef.LT1)
        seen = [
            ref for ref in refs
            if contrast_ratio(colors.get(ref), background) >= _INVISIBLE_CONTRAST
        ]
        return seen or refs

    def dataset(self, ref: str | None) -> Dataset | None:
        return self.content.dataset(ref) if self.content is not None and ref else None

    def image(self, block: ImageBlock) -> str:
        asset = self.content.asset(block.asset_ref or "") if self.content else None
        if asset is None:
            return ""
        path = Path(asset.path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        fit = "cover" if block.fit is ImageFit.COVER else "contain"
        return (
            f'<img src="data:{mime};base64,{data}" '
            f'alt="{escape(block.alt_text or "", quote=True)}" '
            f'style="object-fit: {fit}">'
        )

    def table(self, block: TableBlock) -> str:
        cells = table_cells(block, self.dataset(block.dataset_ref))
        header = block.first_row_header and table_has_header(block)
        head = ""
        if header:
            head = (
                "<thead><tr>" + "".join(f"<th>{escape(c)}</th>" for c in cells[0]) + "</tr></thead>"
            )
            cells = cells[1:]
        rows = "".join(
            "<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in cells
        )
        banded = ' class="banded"' if block.banding else ""
        return f"<table{banded}>{head}<tbody>{rows}</tbody></table>"

    def kpi(self, block: KpiBlock, size_pt: float) -> str:
        value_step = self.step(TextRole.SUBTITLE)
        label_step = self.step(TextRole.CAPTION)
        label_size = label_step.size_pt if label_step else size_pt
        label_color = _var(label_step.color_ref if label_step else None)
        columns = "".join(
            "<div>"
            f'<div class="kpi-value" style="color: {_var(item.color_ref or ColorRef.ACCENT1)}">'
            f"{escape(item.value)}</div>"
            f'<div class="kpi-label" style="color: {label_color}; '
            f'font-size: {self.font_size(label_size)}">{escape(item.label)}</div>'
            "</div>"
            for item in block.items
        )
        weight = "bold" if value_step and value_step.bold else "normal"
        return (
            f'<div class="kpi-row" style="font-size: {self.font_size(size_pt)}; '
            f'font-weight: {weight}">{columns}</div>'
        )

    def chart(self, block: ChartBlock, dataset: Dataset, box: BBox) -> str:
        width = _SVG_WIDTH
        height = round(_SVG_WIDTH * box.cy / box.cx)
        scale = _SVG_WIDTH / box.cx
        caption = self.step(TextRole.CAPTION)
        size_pt = caption.size_pt if caption else min(self.manifest.size_ladder_pt)
        font = size_pt * EMU_PER_PT * scale
        refs = self.visible(
            block.series_color_refs or self.manifest.chart_defaults.series_color_refs or _ACCENTS
        )
        text_color = _var(caption.color_ref if caption else None)
        chart = _SvgChart(block, dataset, width, height, font, refs, text_color)
        return chart.render()


class _SvgChart:
    """Нативная диаграмма в SVG: столбцы, полосы, линии, области, круговые, точки."""

    def __init__(
        self,
        block: ChartBlock,
        dataset: Dataset,
        width: int,
        height: int,
        font: float,
        refs: list[ColorRef],
        text_color: str,
    ) -> None:
        self.block, self.dataset = block, dataset
        self.width, self.height, self.font = width, height, font
        self.refs, self.text_color = refs, text_color
        self.parts: list[str] = []

    def color(self, index: int) -> str:
        return _var(self.refs[index % len(self.refs)])

    def text(self, x: float, y: float, value: str, anchor: str = "middle") -> None:
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{self.font:.1f}" text-anchor="{anchor}" '
            f'style="fill: {self.text_color}">{escape(value)}</text>'
        )

    def render(self) -> str:
        kind = self.block.chart_type
        if kind in _ROUND:
            self.round()
        elif kind is ChartType.SCATTER:
            self.scatter()
        else:
            self.cartesian()
        if self.block.legend:
            self.legend()
        return (
            f'<svg viewBox="0 0 {self.width} {self.height}" role="img" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'aria-label="{escape(self.dataset.title, quote=True)}">'
            + "".join(self.parts)
            + "</svg>"
        )

    # геометрия области построения
    @property
    def plot(self) -> tuple[float, float, float, float]:
        left = self.width * _PLOT_LEFT
        top = self.height * _PLOT_TOP
        right = self.width * (1 - _PLOT_RIGHT)
        bottom = self.height * (1 - _PLOT_BOTTOM)
        return left, top, right, bottom

    def value_range(self, stacked: bool) -> tuple[float, float]:
        if stacked:
            totals = [
                sum(v for s in self.dataset.series if (v := s.values[i]) is not None and v > 0)
                for i in range(len(self.dataset.categories))
            ]
            lows = [
                sum(v for s in self.dataset.series if (v := s.values[i]) is not None and v < 0)
                for i in range(len(self.dataset.categories))
            ]
            return min([0.0, *lows]), max([0.0, *totals])
        values = [v for s in self.dataset.series for v in s.values if v is not None]
        return min([0.0, *values]), max([0.0, *values])

    def cartesian(self) -> None:
        kind = self.block.chart_type
        left, top, right, bottom = self.plot
        stacked = kind in _STACKED
        low, high = self.value_range(stacked)
        span = (high - low) or 1.0
        categories = self.dataset.categories
        horizontal = kind in _HORIZONTAL

        def value_pos(value: float) -> float:
            share = (value - low) / span
            return left + share * (right - left) if horizontal else bottom - share * (bottom - top)

        zero = value_pos(0.0)
        axis = (
            f'<line x1="{zero:.1f}" y1="{top:.1f}" x2="{zero:.1f}" y2="{bottom:.1f}"'
            if horizontal
            else f'<line x1="{left:.1f}" y1="{zero:.1f}" x2="{right:.1f}" y2="{zero:.1f}"'
        )
        self.parts.append(axis + f' style="stroke: {self.text_color}" stroke-width="1"/>')
        unit = self.block.axis_titles.get("value") or self.dataset.unit
        if unit:
            self.text(left, top - self.font * 0.4, unit, anchor="start")

        slot = ((bottom - top) if horizontal else (right - left)) / len(categories)
        for i, category in enumerate(categories):
            center = (top if horizontal else left) + slot * (i + 0.5)
            if horizontal:
                self.text(left - self.font * 0.3, center + self.font * 0.35, category, "end")
            else:
                self.text(center, bottom + self.font * 1.2, category)

        if kind in _LINES:
            self.lines(slot, value_pos)
        else:
            self.bars(slot, value_pos, horizontal, stacked)

    def bars(self, slot: float, position: Position, horizontal: bool, stacked: bool) -> None:
        left, top, _, _ = self.plot
        series = self.dataset.series
        group = slot * _BAR_GROUP_SHARE
        thickness = group if stacked else group / len(series)
        for c in range(len(self.dataset.categories)):
            start = (top if horizontal else left) + slot * c + (slot - group) / 2
            base_pos = base_neg = 0.0
            for s_index, s in enumerate(series):
                value = s.values[c]
                if value is None:
                    continue
                if stacked:
                    begin = base_pos if value >= 0 else base_neg
                    end = begin + value
                    if value >= 0:
                        base_pos = end
                    else:
                        base_neg = end
                    offset = start
                else:
                    begin, end = 0.0, value
                    offset = start + thickness * s_index
                a, b = position(begin), position(end)
                if horizontal:
                    x, w, y, h = min(a, b), abs(b - a), offset, thickness
                else:
                    x, w, y, h = offset, thickness, min(a, b), abs(b - a)
                self.parts.append(
                    f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                    f'style="fill: {self.color(s_index)}"/>'
                )
                if self.block.data_labels and not stacked:
                    if horizontal:
                        self.text(
                            x + w + self.font * 0.3,
                            y + h / 2 + self.font * 0.35,
                            format_number(value),
                            "start",
                        )
                    else:
                        self.text(x + w / 2, y - self.font * 0.3, format_number(value))

    def lines(self, slot: float, position: Position) -> None:
        left, _, _, bottom = self.plot
        kind = self.block.chart_type
        for s_index, s in enumerate(self.dataset.series):
            points = [
                (left + slot * (i + 0.5), position(v))
                for i, v in enumerate(s.values)
                if v is not None
            ]
            if not points:
                continue
            coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
            color = self.color(s_index)
            if kind is ChartType.AREA:
                polygon = (
                    f"{points[0][0]:.1f},{bottom:.1f} {coords} {points[-1][0]:.1f},{bottom:.1f}"
                )
                self.parts.append(
                    f'<polygon class="area" points="{polygon}" style="fill: {color}; '
                    'fill-opacity: 0.35"/>'
                )
            self.parts.append(
                f'<polyline class="line" points="{coords}" style="fill: none; stroke: {color}" '
                f'stroke-width="{_LINE_WIDTH}"/>'
            )
            if kind is ChartType.LINE_MARKERS:
                for x, y in points:
                    self.parts.append(
                        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{_MARKER_RADIUS}" '
                        f'style="fill: {color}"/>'
                    )

    def round(self) -> None:
        left, top, right, bottom = self.plot
        cx, cy = (left + right) / 2, (top + bottom) / 2
        radius = min(right - left, bottom - top) / 2
        values = [max(0.0, v or 0.0) for v in self.dataset.series[0].values]
        total = sum(values) or 1.0
        angle = -math.pi / 2
        hole = radius * _DOUGHNUT_HOLE if self.block.chart_type is ChartType.DOUGHNUT else 0.0
        for index, value in enumerate(values):
            sweep = value / total * 2 * math.pi
            end = angle + sweep
            large = 1 if sweep > math.pi else 0
            outer = (
                f"M {cx + radius * math.cos(angle):.1f} {cy + radius * math.sin(angle):.1f} "
                f"A {radius:.1f} {radius:.1f} 0 {large} 1 "
                f"{cx + radius * math.cos(end):.1f} {cy + radius * math.sin(end):.1f}"
            )
            if hole:
                path = (
                    f"{outer} L {cx + hole * math.cos(end):.1f} {cy + hole * math.sin(end):.1f} "
                    f"A {hole:.1f} {hole:.1f} 0 {large} 0 "
                    f"{cx + hole * math.cos(angle):.1f} {cy + hole * math.sin(angle):.1f} Z"
                )
            else:
                path = f"{outer} L {cx:.1f} {cy:.1f} Z"
            self.parts.append(f'<path class="slice" d="{path}" style="fill: {self.color(index)}"/>')
            if self.block.data_labels and value:
                middle = angle + sweep / 2
                distance = (radius + hole) / 2 if hole else radius * 0.6
                self.text(
                    cx + distance * math.cos(middle),
                    cy + distance * math.sin(middle),
                    format_number(value),
                )
            angle = end

    def scatter(self) -> None:
        left, top, right, bottom = self.plot
        xs = [float(c.replace(",", ".").replace(" ", "")) for c in self.dataset.categories]
        ys = [v for s in self.dataset.series for v in s.values if v is not None]
        x_low, x_high = min(xs), max(xs)
        y_low, y_high = min([0.0, *ys]), max([0.0, *ys])
        self.parts.append(
            f'<line x1="{left:.1f}" y1="{bottom:.1f}" x2="{right:.1f}" y2="{bottom:.1f}" '
            f'style="stroke: {self.text_color}"/>'
        )
        for s_index, s in enumerate(self.dataset.series):
            for x, y in zip(xs, s.values, strict=False):
                if y is None:
                    continue
                px = left + (x - x_low) / ((x_high - x_low) or 1.0) * (right - left)
                py = bottom - (y - y_low) / ((y_high - y_low) or 1.0) * (bottom - top)
                self.parts.append(
                    f'<circle class="point" cx="{px:.1f}" cy="{py:.1f}" r="{_POINT_RADIUS}" '
                    f'style="fill: {self.color(s_index)}"/>'
                )

    def legend(self) -> None:
        names = (
            self.dataset.categories
            if self.block.chart_type in _ROUND
            else [s.name for s in self.dataset.series]
        )
        y = self.height - self.font * 0.8
        slot = self.width / max(1, len(names))
        for index, name in enumerate(names):
            x = slot * index + slot / 2 - self.font * 2
            self.parts.append(
                f'<rect x="{x:.1f}" y="{y - self.font * 0.8:.1f}" width="{self.font * 0.8:.1f}" '
                f'height="{self.font * 0.8:.1f}" style="fill: {self.color(index)}"/>'
            )
            self.text(x + self.font * 1.1, y, name, anchor="start")


def export_html(
    deck: DeckIR,
    manifest: TemplateManifest,
    out: Path,
    content: ContentPackage | None = None,
    fonts: FontLibrary | None = None,
) -> Path:
    """Один самодостаточный html на колоду: то же представление, что и в pptx."""
    if deck.template_id != manifest.template_id:
        raise WriterError(
            f"template_id колоды {deck.template_id} не совпадает с манифестом "
            f"{manifest.template_id}"
        )
    degrader = SlideDegrader(manifest, fonts)
    slides = [degrader.degrade(slide, content) for slide in deck.slides]
    validator = SlideValidator(manifest)
    problems = [p for slide in slides for p in validator.problems(slide, content)]
    if problems:
        raise WriterError("\n".join(problems))
    document = _HtmlDeck(manifest, content).document(deck.model_copy(update={"slides": slides}))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    return out
