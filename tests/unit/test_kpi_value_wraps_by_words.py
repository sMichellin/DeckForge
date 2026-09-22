"""Значение показателя переносится по словам, но не по цифрам.
Change `kpi-value-wraps-by-words` (задача B13).

Нарушитель: фразовое значение («часы → минуты») сажало весь блок на тот кегль,
при котором фраза встаёт в одну строку, — 14 pt при списке рядом в 23,4 pt
(VK WorkSpace s04, прогон `6c4277d898c3`). Норма: число одной строкой остаётся,
слово по знакам не рвётся, короткое числовое значение растёт, как в #87.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.enums import TextRole
from deckforge.domain.slide import KpiBlock, KpiItem
from deckforge.domain.template import TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.fitting import fit_kpi
from deckforge.layout.fonts import FontLibrary
from tests.unit.test_layout_fonts import make_font

#: Рамка показателей со слайда-нарушителя: узкая и высокая, места по вертикали вдоволь.
TALL = (12 * EMU_PER_CM, 14 * EMU_PER_CM)


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=500)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=550, bold=True)
    return FontLibrary([tmp_path])


def kpi(*values: str, box: tuple[int, int] = TALL) -> KpiBlock:
    return KpiBlock(
        block_id="k",
        items=[KpiItem(value=value, label="за год") for value in values],
        x=0, y=0, cx=box[0], cy=box[1],
    )


def sizes(manifest: TemplateManifest) -> tuple[float, float]:
    """Кегли ролей `subtitle` и `body` этого шаблона."""
    subtitle = manifest.typography(TextRole.SUBTITLE)
    body = manifest.typography(TextRole.BODY)
    assert subtitle is not None and body is not None
    return subtitle.size_pt, body.size_pt


def test_a_phrase_value_wraps_and_grows(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Нарушитель: фраза в значении не должна тянуть показатель ниже тела слайда."""
    block = kpi("часы → минуты", "100%")
    assert block.bbox is not None

    result = fit_kpi(block, block.bbox, manifest, fonts=fonts)

    _, body_pt = sizes(manifest)
    assert result.overflow is False
    assert result.final_size_pt > body_pt, "показатель набран не крупнее основного текста"
    assert result.final_size_pt == max(manifest.size_ladder_pt)


def test_a_number_still_holds_one_line(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: разряды числа переносить нельзя — блок садится по числу, а не по фразе."""
    block = kpi("часы → минуты", "1 200 000 000 ₽")
    assert block.bbox is not None

    result = fit_kpi(block, block.bbox, manifest, fonts=fonts)

    subtitle_pt, _ = sizes(manifest)
    assert result.overflow is False
    assert result.final_size_pt < subtitle_pt


def test_a_word_is_never_broken_by_characters(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: слово шире колонки — кегль уступает, а не рубит слово пополам."""
    block = kpi("оптимизация", "рост")
    assert block.bbox is not None

    result = fit_kpi(block, block.bbox, manifest, fonts=fonts)

    subtitle_pt, _ = sizes(manifest)
    assert result.final_size_pt == subtitle_pt, "слово разрублено ради крупного кегля"


def test_a_short_number_still_grows(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    """Норма #87: короткое числовое значение в высокой рамке по-прежнему растёт до потолка."""
    block = kpi("37 %", "×2,3")
    assert block.bbox is not None

    result = fit_kpi(block, block.bbox, manifest, fonts=fonts)

    assert result.final_size_pt == max(manifest.size_ladder_pt)
