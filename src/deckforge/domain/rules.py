"""Чистые правила домена: без I/O, без моделей, детерминированные.

Используются и композицией (чтобы не создавать нарушения), и аудитом (чтобы их ловить).
"""

from __future__ import annotations

from deckforge.domain.base import BBox
from deckforge.domain.enums import ChartType
from deckforge.domain.template import TemplateManifest


def relative_luminance(hex_color: str) -> float:
    """WCAG 2.1 relative luminance для #RRGGBB."""
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """Контраст по WCAG: от 1.0 до 21.0."""
    l1, l2 = relative_luminance(fg_hex), relative_luminance(bg_hex)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def meets_wcag_aa(fg_hex: str, bg_hex: str, *, large_text: bool = False) -> bool:
    return contrast_ratio(fg_hex, bg_hex) >= (3.0 if large_text else 4.5)


def delta_e_rgb(a_hex: str, b_hex: str) -> float:
    """Грубое евклидово расстояние в RGB — достаточно для `map_to_nearest_theme_color`."""
    a, b = a_hex.lstrip("#"), b_hex.lstrip("#")
    return sum((int(a[i : i + 2], 16) - int(b[i : i + 2], 16)) ** 2 for i in (0, 2, 4)) ** 0.5


def overlap_ratio(a: BBox, b: BBox) -> float:
    """Доля площади меньшего блока, перекрытая вторым блоком."""
    smaller = min(a.area, b.area)
    return a.intersection_area(b) / smaller if smaller else 0.0


def snap_to_nearest(value: int, guides: list[int], tolerance_emu: int) -> int:
    """Притягивает координату к ближайшей направляющей, если та в пределах допуска."""
    if not guides:
        return value
    nearest = min(guides, key=lambda g: abs(g - value))
    return nearest if abs(nearest - value) <= tolerance_emu else value


def next_size_down(manifest: TemplateManifest, current_pt: float) -> float | None:
    """Следующий кегль вниз по шкале шаблона. Свои значения не изобретаются (ADR-002)."""
    smaller = [s for s in manifest.size_ladder_pt if s < current_pt]
    return max(smaller) if smaller else None


def choose_chart_type(
    *, series_count: int, category_count: int, is_time_series: bool, is_shares: bool
) -> ChartType:
    """Детерминированный выбор типа диаграммы (§10). LLM подключается только на границе."""
    if is_shares and series_count == 1 and 2 <= category_count <= 6:
        return ChartType.DOUGHNUT
    if is_time_series:
        return ChartType.LINE_MARKERS if category_count <= 12 else ChartType.LINE
    if series_count > 1 and category_count <= 8:
        return ChartType.CLUSTERED_COLUMN
    return ChartType.CLUSTERED_BAR if category_count > 8 else ChartType.CLUSTERED_COLUMN


def fill_ratio(blocks: list[BBox], slide: BBox) -> float:
    """Заполненность слайда: сумма площадей блоков к площади слайда."""
    return sum(b.area for b in blocks) / slide.area if slide.area else 0.0
