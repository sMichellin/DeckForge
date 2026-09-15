"""Привязка к теме: `ColorRef` → `MSO_THEME_COLOR`, `FontRef` → гарнитура темы (ADR-002).

Единственное место, где IR-ссылки превращаются в свойства python-pptx.
"""

from __future__ import annotations

from deckforge.domain.enums import ColorRef, FontRef
from deckforge.domain.template import TemplateManifest


def apply_theme_color(font_or_fill: object, ref: ColorRef) -> None:
    """Ставит ссылку на цвет темы, а не RGB — иначе смена шаблона не перекрасит объект."""
    raise NotImplementedError("change (13) pptx-writer")


def resolve_font(ref: FontRef, manifest: TemplateManifest) -> str:
    raise NotImplementedError("change (13) pptx-writer")
