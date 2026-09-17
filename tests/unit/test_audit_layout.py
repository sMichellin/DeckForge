"""Проверки вёрстки: на нарушителе и на норме. Change (15).

Второй тест — на норме — здесь не формальность. Проверка, которая ловит всё подряд,
выглядит работающей ровно до того момента, когда отчёт открывает человек: сотня находок
на правильном слайде приучает игнорировать отчёт целиком, и вместе с ложной
срабатывает каждая настоящая.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.audit.deterministic.layout import (
    image_aspect_distorted,
    margin_violation,
    off_guides,
    out_of_bounds,
    overlap,
    text_clipped,
    text_overflow,
)
from deckforge.audit.registry import CheckUnavailable
from deckforge.domain.slide import FitResult
from deckforge.domain.template import Grid, TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide, title


def test_out_of_bounds_catches_block_past_the_canvas(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body(box=(30, 1, 10, 3))))
    findings = list(out_of_bounds(context_for("layout.out_of_bounds", colony, manifest)))
    assert [f.block_id for f in findings] == ["b2"]
    assert findings[0].bbox_emu is not None


def test_out_of_bounds_silent_on_a_block_inside(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body(box=(3, 3, 10, 3))))
    assert list(out_of_bounds(context_for("layout.out_of_bounds", colony, manifest))) == []


def test_overlap_catches_two_blocks_on_top_of_each_other(manifest: TemplateManifest) -> None:
    first = body("Первый", block_id="b1", box=(3, 3, 6, 3))
    second = body("Второй", block_id="b2", box=(3, 3, 6, 3))
    colony = deck(slide(first, second))
    findings = list(overlap(context_for("layout.overlap", colony, manifest)))
    assert len(findings) == 1
    assert findings[0].evidence["other_block_id"] == "b2"


def test_overlap_silent_on_blocks_side_by_side(manifest: TemplateManifest) -> None:
    left = body("Слева", block_id="b1", box=(1, 3, 3, 2))
    right = body("Справа", block_id="b2", box=(8, 3, 3, 2))
    colony = deck(slide(left, right))
    assert list(overlap(context_for("layout.overlap", colony, manifest))) == []


def test_text_overflow_trusts_the_measurement_from_fitting(manifest: TemplateManifest) -> None:
    """Если вёрстка уже померила блок (change 12), оценка по вместимости не нужна."""
    colony = deck(
        slide(
            title(),
            body("Короткий текст"),
            fit_report={"b2": FitResult(final_size_pt=18, overflow=True)},
        )
    )
    findings = list(text_overflow(context_for("layout.text_overflow", colony, manifest)))
    assert [f.evidence["source"] for f in findings] == ["fit_report"]


def test_text_overflow_falls_back_to_layout_capacity(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("а" * 500)))
    findings = list(text_overflow(context_for("layout.text_overflow", colony, manifest)))
    assert [f.evidence["source"] for f in findings] == ["capacity"]
    assert findings[0].evidence["limit"] == "420"


def test_text_overflow_silent_when_text_fits(manifest: TemplateManifest) -> None:
    colony = deck(
        slide(
            title(),
            body("Короткий тезис"),
            fit_report={"b2": FitResult(final_size_pt=18, overflow=False)},
        )
    )
    assert list(text_overflow(context_for("layout.text_overflow", colony, manifest))) == []


def test_text_clipped_catches_a_block_crossing_the_edge(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Текст у края", box=(30, 1, 10, 3))))
    findings = list(text_clipped(context_for("layout.text_clipped", colony, manifest)))
    assert [f.block_id for f in findings] == ["b2"]


def test_text_clipped_silent_on_a_block_inside(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Текст", box=(3, 3, 8, 3))))
    assert list(text_clipped(context_for("layout.text_clipped", colony, manifest))) == []


def _with_guides(manifest: TemplateManifest) -> TemplateManifest:
    grid = Grid(
        margins_emu=manifest.grid.margins_emu,
        guides_x_emu=[manifest.grid.margins_emu.left],
        guides_y_emu=[1_800_000],
        columns=manifest.grid.columns,
        gutter_emu=manifest.grid.gutter_emu,
        guides_source="xml",
    )
    return manifest.model_copy(update={"grid": grid})


def test_off_guides_catches_a_near_miss(manifest: TemplateManifest) -> None:
    """Промах на 20 000 EMU: меньше допуска, но не ноль — значит рука дрогнула."""
    with_guides = _with_guides(manifest)
    near = manifest.grid.margins_emu.left + 20_000
    colony = deck(slide(body("Текст", box=(near / 360_000, 5, 8, 3))))
    findings = list(off_guides(context_for("layout.off_guides", colony, with_guides)))
    assert [f.evidence["axis"] for f in findings] == ["x"]


def test_off_guides_silent_when_block_sits_on_the_guide(manifest: TemplateManifest) -> None:
    with_guides = _with_guides(manifest)
    colony = deck(slide(body("Текст", box=(2, 5, 8, 3))))
    assert list(off_guides(context_for("layout.off_guides", colony, with_guides))) == []


def test_off_guides_is_unavailable_without_guides(manifest: TemplateManifest) -> None:
    """Направляющих нет — проверка не запускалась, а не «нарушений не найдено».

    Пустой список означал бы, что выравнивание проверено и в порядке. Прогон ловит
    это исключение и пишет проверку в пропущенные.
    """
    colony = deck(slide(body("Текст", box=(2.06, 5, 8, 3))))
    with pytest.raises(CheckUnavailable):
        list(off_guides(context_for("layout.off_guides", colony, manifest)))


def test_margin_violation_catches_content_in_the_margin(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("В поле", box=(0.5, 2, 5, 3))))
    findings = list(margin_violation(context_for("layout.margin_violation", colony, manifest)))
    assert [f.block_id for f in findings] == ["b2"]


def test_margin_violation_allows_a_full_bleed_block(manifest: TemplateManifest) -> None:
    """Плашка в край — приём шаблона, а не отмена полей для текста."""
    colony = deck(slide(body("Подложка", box=(0, 0, 35.4, 19))))
    assert list(margin_violation(context_for("layout.margin_violation", colony, manifest))) == []


def _deck_with_picture(path: Path, *, width_emu: int, height_emu: int) -> None:
    pptx = pytest.importorskip("pptx")
    pil = pytest.importorskip("PIL.Image")

    image_path = path.parent / "picture.png"
    pil.new("RGB", (100, 50), "white").save(image_path)

    presentation = pptx.Presentation()
    layout = presentation.slide_layouts[6]
    slide_obj = presentation.slides.add_slide(layout)
    slide_obj.shapes.add_picture(
        str(image_path), 0, 0, width=width_emu, height=height_emu
    )
    presentation.save(str(path))


def test_image_aspect_distorted_catches_a_stretched_picture(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Картинка 100×50 растянута в квадрат: пропорция 1.0 против исходной 2.0."""
    path = tmp_path / "deck.pptx"
    _deck_with_picture(path, width_emu=3_600_000, height_emu=3_600_000)
    colony = deck(slide(title()))
    context = context_for(
        "layout.image_aspect_distorted", colony, manifest, deck_path=path
    )
    findings = list(image_aspect_distorted(context))
    assert len(findings) == 1
    assert findings[0].evidence["natural"] == "2.000"


def test_image_aspect_distorted_silent_on_correct_proportions(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    path = tmp_path / "deck.pptx"
    _deck_with_picture(path, width_emu=3_600_000, height_emu=1_800_000)
    colony = deck(slide(title()))
    context = context_for(
        "layout.image_aspect_distorted", colony, manifest, deck_path=path
    )
    assert list(image_aspect_distorted(context)) == []


def test_image_aspect_distorted_is_unavailable_without_a_file(
    manifest: TemplateManifest,
) -> None:
    """Файла нет — проверка не запускалась: растяжение видно только в готовом .pptx."""
    colony = deck(slide(title()))
    context = context_for("layout.image_aspect_distorted", colony, manifest)
    with pytest.raises(CheckUnavailable):
        list(image_aspect_distorted(context))
