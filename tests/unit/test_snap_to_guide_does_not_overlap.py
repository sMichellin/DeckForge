"""Подтяжка к направляющей не сажает блок на соседа.
Change `snap-to-guide-does-not-overlap` (задача B12).

Нарушитель: направляющая шаблона проходит выше рамки заголовка, и `snap_to_guide`
затаскивал под неё свободный блок — предупреждение `layout.off_guides` менялось
на ошибку `layout.overlap` (VK Tech s04 и s09, прогон `5507bff9e589`: направляющая
1,98 см против рамки заголовка до 2,08 см). Норма: подтяжка вдали от соседей,
подтяжка «не глубже, чем было» и подложка во весь слайд работают как прежде.
"""

from __future__ import annotations

import pytest

from deckforge.audit.deterministic.layout import off_guides
from deckforge.audit.fixes import FixApplier
from deckforge.domain.audit import Finding
from deckforge.domain.enums import ImageFit, ImageSource
from deckforge.domain.slide import ImageBlock
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import bullets, cm, context_for, deck, slide, title

#: Рамка заголовка синтетического макета: y от 1 до 4 см (см. `tests/conftest.py`).
TITLE_BOTTOM_CM = 4.0


def aligned(manifest: TemplateManifest, *, guide_y_cm: float) -> TemplateManifest:
    """Манифест с одной горизонтальной направляющей; по x направляющая совпадает с блоком."""
    grid = manifest.grid.model_copy(
        update={"guides_x_emu": [cm(3)], "guides_y_emu": [cm(guide_y_cm)]}
    )
    return manifest.model_copy(update={"grid": grid})


def findings_for(block_id: str, colony: object, manifest: TemplateManifest) -> list[Finding]:
    found = off_guides(context_for("layout.off_guides", colony, manifest))  # type: ignore[arg-type]
    return [f for f in found if f.block_id == block_id]


def backdrop() -> ImageBlock:
    """Подложка во весь слайд: приём шаблона, а не сосед."""
    return ImageBlock(
        block_id="bg", source=ImageSource.ASSET, asset_ref="a001", fit=ImageFit.COVER,
        x=0, y=0, cx=35 * cm(1) + cm(0.4), cy=19 * cm(1),
    )


def test_a_guide_above_the_title_frame_is_refused(manifest: TemplateManifest) -> None:
    """Нарушитель: направляющая выше рамки заголовка — блок остаётся на месте."""
    template = aligned(manifest, guide_y_cm=TITLE_BOTTOM_CM - 0.05)
    colony = deck(slide(title(), bullets("раз", "два", box=(3, TITLE_BOTTOM_CM + 0.05, 8, 3))))
    found = findings_for("b2", colony, template)
    assert [f.evidence["axis"] for f in found] == ["y"]

    fixed, report = FixApplier().apply(colony, found, template)

    assert fixed.slides[0].block("b2").y == cm(TITLE_BOTTOM_CM + 0.05), "блок заехал на заголовок"
    assert report.findings[0].auto_fix_applied is False
    assert "b1" in report.findings[0].evidence["fix_skipped"]


def test_a_guide_clear_of_the_neighbours_still_pulls(manifest: TemplateManifest) -> None:
    """Норма: соседей рядом нет — подтяжка работает, как до правки."""
    template = aligned(manifest, guide_y_cm=6)
    colony = deck(slide(title(), bullets("раз", "два", box=(3, 6.05, 8, 3))))
    found = findings_for("b2", colony, template)

    fixed, report = FixApplier().apply(colony, found, template)

    assert fixed.slides[0].block("b2").y == cm(6)
    assert report.findings[0].auto_fix_applied is True


def test_a_block_already_on_its_neighbour_may_still_be_pulled(
    manifest: TemplateManifest
) -> None:
    """Норма: блок уже лежит на заголовке — подтяжка вниз наложение уменьшает, значит можно."""
    template = aligned(manifest, guide_y_cm=3.15)
    colony = deck(slide(title(), bullets("раз", "два", box=(3, 3.05, 8, 3))))
    found = findings_for("b2", colony, template)

    fixed, report = FixApplier().apply(colony, found, template)

    assert fixed.slides[0].block("b2").y == cm(3.15)
    assert report.findings[0].auto_fix_applied is True


def test_a_full_bleed_backdrop_is_not_a_neighbour(manifest: TemplateManifest) -> None:
    """Норма: подложка во весь слайд лежит под контентом по замыслу и подтяжке не мешает."""
    template = aligned(manifest, guide_y_cm=6)
    colony = deck(slide(backdrop(), title(), bullets("раз", "два", box=(3, 6.05, 8, 3))))
    found = findings_for("b2", colony, template)

    fixed, report = FixApplier().apply(colony, found, template)

    assert fixed.slides[0].block("b2").y == cm(6)
    assert [f.auto_fix_applied for f in report.findings] == [True]


@pytest.mark.parametrize("guide_y_cm", [TITLE_BOTTOM_CM - 0.05, 6])
def test_the_finding_is_never_lost(manifest: TemplateManifest, guide_y_cm: float) -> None:
    """И при отказе, и при успехе находка остаётся в отчёте с проставленным исходом."""
    template = aligned(manifest, guide_y_cm=guide_y_cm)
    colony = deck(slide(title(), bullets("раз", "два", box=(3, guide_y_cm + 0.1, 8, 3))))
    found = findings_for("b2", colony, template)

    _, report = FixApplier().apply(colony, found, template)

    assert len(report.findings) == 1
    assert report.findings[0].auto_fix_applied is not None
