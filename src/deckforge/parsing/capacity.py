"""Вместимость макета из метрик шрифта и площади плейсхолдера. Change (3)/(12).

Значения вычисляются, а не задаются константами (C6).
"""

from __future__ import annotations

from deckforge.domain.template import LayoutCapacity, LayoutSpec, TemplateManifest


def compute_capacity(layout: LayoutSpec, manifest: TemplateManifest) -> LayoutCapacity:
    raise NotImplementedError("change (3) template-parsing-core")
