"""Перечисления домена. Значения — часть публичного контракта (JSON-схемы)."""

from __future__ import annotations

from enum import StrEnum


class LayoutKind(StrEnum):
    """Семантический тип макета шаблона. Определяется классификатором, не именем макета."""

    TITLE = "title"
    SECTION = "section"
    BULLETS = "bullets"
    TWO_COLUMN = "two_column"
    CHART = "chart"
    TABLE = "table"
    KPI = "kpi"
    QUOTE = "quote"
    IMAGE_FULL = "image_full"
    CLOSING = "closing"
    CUSTOM = "custom"


class TextRole(StrEnum):
    """Роль в типографической шкале шаблона."""

    TITLE = "title"
    SUBTITLE = "subtitle"
    BODY = "body"
    CAPTION = "caption"


class ColorRef(StrEnum):
    """Имена цветов схемы темы. RGB-литералы в IR запрещены (ADR-002)."""

    DK1 = "dk1"
    LT1 = "lt1"
    DK2 = "dk2"
    LT2 = "lt2"
    ACCENT1 = "accent1"
    ACCENT2 = "accent2"
    ACCENT3 = "accent3"
    ACCENT4 = "accent4"
    ACCENT5 = "accent5"
    ACCENT6 = "accent6"
    HLINK = "hlink"
    FOL_HLINK = "folHlink"


class FontRef(StrEnum):
    """Имена гарнитур схемы темы."""

    MAJOR_LATIN = "major_latin"
    MINOR_LATIN = "minor_latin"
    MAJOR_CS = "major_cs"
    MINOR_CS = "minor_cs"


class BlockType(StrEnum):
    TEXT = "text"
    BULLETS = "bullets"
    CHART = "chart"
    TABLE = "table"
    SMARTART = "smartart"
    ICON = "icon"
    IMAGE = "image"
    KPI = "kpi"
    QUOTE = "quote"
    CALLOUT = "callout"


class CalloutTone(StrEnum):
    """Вид callout. Набор закрыт: это часть контракта, а не вкус композитора (DG4).

    Цвет и подпись вида решает вёрстка по дизайн-системе, а не модель.
    """

    INSIGHT = "insight"
    RISK = "risk"


class ListStyle(StrEnum):
    """Стиль списка (DG3, `compose-by-the-design-system`). Набор закрыт, как у callout.

    Композиция выбирает стиль по смыслу пунктов, а знак, цвет и отступ рисует вёрстка
    по дизайн-системе шаблона. Не задан — маркированный, как было до этого поля.
    """

    BULLETED = "bulleted"
    NUMBERED = "numbered"
    ICON = "icon"


class ChartType(StrEnum):
    CLUSTERED_BAR = "clustered_bar"
    STACKED_BAR = "stacked_bar"
    CLUSTERED_COLUMN = "clustered_column"
    STACKED_COLUMN = "stacked_column"
    LINE = "line"
    LINE_MARKERS = "line_markers"
    PIE = "pie"
    DOUGHNUT = "doughnut"
    SCATTER = "scatter"
    AREA = "area"


class SmartArtPattern(StrEnum):
    """Составные компоненты из автофигур (§10) — не OOXML DrawingML diagram."""

    PROCESS = "process"
    CYCLE = "cycle"
    HIERARCHY = "hierarchy"
    PYRAMID = "pyramid"
    TIMELINE = "timeline"
    MATRIX = "matrix"


class ImageFit(StrEnum):
    COVER = "cover"
    CONTAIN = "contain"


class ImageSource(StrEnum):
    ASSET = "asset"
    GENERATED = "generated"


class SlideIntent(StrEnum):
    """Роль слайда в нарративе колоды."""

    TITLE = "title"
    AGENDA = "agenda"
    PROBLEM = "problem"
    SOLUTION = "solution"
    EVIDENCE = "evidence"
    COMPARISON = "comparison"
    PROCESS = "process"
    METRICS = "metrics"
    ROADMAP = "roadmap"
    SECTION = "section"
    SUMMARY = "summary"
    CLOSING = "closing"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AutoFix(StrEnum):
    SHRINK_FONT = "shrink_font"
    SPLIT_SLIDE = "split_slide"
    SNAP_TO_GUIDE = "snap_to_guide"
    MAP_TO_NEAREST_THEME_COLOR = "map_to_nearest_theme_color"
    REGENERATE_HEADLINE = "regenerate_headline"
    SHORTEN_TEXT = "shorten_text"
    NONE = "none"


class Density(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExportFormat(StrEnum):
    PPTX = "pptx"
    PDF = "pdf"
    HTML = "html"
