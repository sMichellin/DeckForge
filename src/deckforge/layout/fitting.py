"""Авто-кегль и стратегия вписывания. Change (12) `layout-fitting`.

Порядок деградации (из METHOD прежнего проекта, переписано без брендовых констант):
1. как есть → 2. ступень кегля вниз по шкале шаблона → 3. сокращение текста LLM →
4. деление слайда надвое. Заголовок не уменьшается никогда.
"""

from __future__ import annotations

from deckforge.domain.base import BBox
from deckforge.domain.slide import FitResult
from deckforge.domain.template import TemplateManifest


def fit_text(
    text: str,
    *,
    box: BBox,
    manifest: TemplateManifest,
    start_size_pt: float,
    font_family: str,
    allow_shrink: bool = True,
) -> FitResult:
    raise NotImplementedError("change (12) layout-fitting")
