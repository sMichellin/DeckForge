"""Схема, не влезшая в свою рамку, не роняет запись колоды.

Прогон VK Education add3de1e5918: схеме `process` досталась полоса 30 × 1,5 см, подписи
не встали ни в каком кегле, и писатель отверг блок со стратегией `split` — прогон упал.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import SmartArtPattern, TextRole
from deckforge.domain.slide import BulletsBlock, SlideIR, SmartArtBlock, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.nodes.fit import _fit_shortening
from tests.unit.test_layout_fonts import make_font

CONTENT = ContentPackage(brief=Brief(purpose="report", audience="правление", target_slides=5))
TITLE = TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги года")
STEPS = ["Разобрать шаблон", "Понять логику слайдов", "Подобрать паттерн", "Сверстать"]


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=500)
    return FontLibrary([tmp_path])


def _slide(manifest: TemplateManifest, cy: int, cx: int | None = None) -> SlideIR:
    area = manifest.content_bbox
    scheme = SmartArtBlock(
        block_id="s", pattern=SmartArtPattern.PROCESS, items=STEPS,
        x=area.x, y=area.bottom - cy, cx=cx or area.cx, cy=cy,
    )
    return SlideIR(slide_id="s05", layout_id="L07", variant="A", blocks=[TITLE, scheme])


def test_scheme_in_a_strip_becomes_a_list_and_fits(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Нарушитель: полоса в строку. Схема — список, лишние пункты сняты, переполнения нет."""
    tight = _slide(manifest, 300_000, manifest.content_bbox.cx // 3)
    fitted, notes = _fit_shortening(tight, manifest, fonts, CONTENT)

    block = next(b for b in fitted.blocks if b.block_id == "s")
    assert isinstance(block, BulletsBlock)
    assert fitted.fit_report["s"].overflow is False
    assert [item.text for item in block.items] == STEPS[: len(block.items)]
    assert any("записана списком" in note for note in notes)


def test_scheme_with_room_stays_a_scheme(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    """Норма: место есть — схема остаётся схемой, заметки о списке нет."""
    fitted, notes = _fit_shortening(
        _slide(manifest, manifest.content_bbox.cy // 2), manifest, fonts, CONTENT
    )

    assert isinstance(next(b for b in fitted.blocks if b.block_id == "s"), SmartArtBlock)
    assert not any("записана списком" in note for note in notes)
