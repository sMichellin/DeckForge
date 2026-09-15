"""`SlideIR` → .pptx. Change (13) `pptx-writer`.

Инварианты рендерера (ADR-002):
* слайд создаётся **только** на макете из шаблона: `prs.slide_layouts[layout.index]`;
* текст кладётся в плейсхолдеры, а не в новые текстбоксы, где плейсхолдер есть;
* цвет задаётся ссылкой на тему (`MSO_THEME_COLOR`), не литеральным RGB;
* кегль берётся из `manifest.typography_scale`, не подбирается на глаз.
Любой литерал RGB/шрифта/EMU в этом модуле — ошибка линтера `lint_no_template_constants`.
"""

from __future__ import annotations

from pathlib import Path

from deckforge.domain.slide import DeckIR, SlideIR
from deckforge.domain.template import TemplateManifest


class PptxWriter:
    def __init__(self, template_path: Path, manifest: TemplateManifest) -> None:
        self.template_path = template_path
        self.manifest = manifest

    def validate(self, slide: SlideIR) -> None:
        """Инварианты §4.4: макет есть в манифесте, placeholder_idx существует,
        координаты внутри полей, цвета — только `color_ref`."""
        raise NotImplementedError("change (13) pptx-writer")

    def write(self, deck: DeckIR, out_path: Path) -> Path:
        raise NotImplementedError("change (13) pptx-writer")
