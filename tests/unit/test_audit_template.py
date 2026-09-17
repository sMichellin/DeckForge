"""Проверки соответствия шаблону: на нарушителе и на норме. Change (15)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.audit.deterministic.template import (
    color_not_in_palette,
    contrast_below_wcag,
    decor_moved,
    font_not_in_theme,
    layout_not_from_template,
    size_not_in_scale,
)
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import Decor, DecorElement, TemplateManifest, TypographyStep
from tests.unit._audit_builders import body, chart, context_for, deck, slide, title


def test_font_not_in_theme_catches_a_third_family(manifest: TemplateManifest) -> None:
    """Порог занижен до одной гарнитуры: в колоде их две, заголовочная и текстовая."""
    colony = deck(slide(title(), body()))
    context = context_for("template.font_not_in_theme", colony, manifest, max_families=1)
    findings = list(font_not_in_theme(context))
    assert [f.evidence.get("families") for f in findings if "families" in f.evidence]


def test_font_not_in_theme_silent_within_the_limit(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body()))
    context = context_for("template.font_not_in_theme", colony, manifest)
    assert list(font_not_in_theme(context)) == []


def test_font_not_in_theme_catches_a_foreign_font_in_the_file(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Чужая гарнитура появляется при записи файла — там её и надо искать.

    По `SlideIR` эту проверку сделать нельзя: имени гарнитуры в IR нет, а гарнитура
    плейсхолдера принадлежит шаблону по построению.
    """
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "deck.pptx"
    presentation = pptx.Presentation()
    slide_obj = presentation.slides.add_slide(presentation.slide_layouts[5])
    run = slide_obj.shapes.title.text_frame.paragraphs[0].add_run()
    run.text = "Заголовок чужой гарнитурой"
    run.font.name = "Comic Sans MS"
    presentation.save(str(path))

    colony = deck(slide(title()))
    context = context_for("template.font_not_in_theme", colony, manifest, deck_path=path)
    findings = list(font_not_in_theme(context))
    assert "Comic Sans MS" in {f.evidence.get("family") for f in findings}


def test_font_not_in_theme_silent_when_file_uses_template_fonts(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "deck.pptx"
    presentation = pptx.Presentation()
    slide_obj = presentation.slides.add_slide(presentation.slide_layouts[5])
    run = slide_obj.shapes.title.text_frame.paragraphs[0].add_run()
    run.text = "Заголовок гарнитурой шаблона"
    run.font.name = manifest.theme.fonts.major_latin
    presentation.save(str(path))

    colony = deck(slide(title()))
    context = context_for("template.font_not_in_theme", colony, manifest, deck_path=path)
    assert list(font_not_in_theme(context)) == []


def test_size_not_in_scale_catches_a_size_off_the_ladder(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Тезис", size_pt=17)))
    findings = list(size_not_in_scale(context_for("template.size_not_in_scale", colony, manifest)))
    assert [f.evidence["size_pt"] for f in findings] == ["17"]


def test_size_not_in_scale_silent_on_a_size_from_the_ladder(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Тезис", size_pt=18)))
    context = context_for("template.size_not_in_scale", colony, manifest)
    assert list(size_not_in_scale(context)) == []


def test_color_not_in_palette_catches_two_series_of_one_colour(
    manifest: TemplateManifest,
) -> None:
    colony = deck(slide(chart(series_color_refs=[ColorRef.ACCENT1, ColorRef.ACCENT1])))
    findings = list(
        color_not_in_palette(context_for("template.color_not_in_palette", colony, manifest))
    )
    assert [f.evidence.get("duplicates") for f in findings] == ["accent1"]


def test_color_not_in_palette_silent_on_distinct_series(manifest: TemplateManifest) -> None:
    colony = deck(slide(chart(series_color_refs=[ColorRef.ACCENT1, ColorRef.ACCENT2])))
    context = context_for("template.color_not_in_palette", colony, manifest)
    assert list(color_not_in_palette(context)) == []


def test_layout_not_from_template_catches_an_unknown_layout(
    manifest: TemplateManifest,
) -> None:
    colony = deck(slide(title(), layout_id="L99"))
    context = context_for("template.layout_not_from_template", colony, manifest)
    findings = list(layout_not_from_template(context))
    assert [f.evidence["layout_id"] for f in findings] == ["L99"]


def test_layout_not_from_template_catches_a_missing_placeholder(
    manifest: TemplateManifest,
) -> None:
    colony = deck(slide(body("Текст", placeholder_idx=7)))
    context = context_for("template.layout_not_from_template", colony, manifest)
    findings = list(layout_not_from_template(context))
    assert [f.evidence["placeholder_idx"] for f in findings] == ["7"]


def test_layout_not_from_template_silent_on_a_template_layout(
    manifest: TemplateManifest,
) -> None:
    colony = deck(slide(title(), body()))
    context = context_for("template.layout_not_from_template", colony, manifest)
    assert list(layout_not_from_template(context)) == []


def _with_logo(manifest: TemplateManifest) -> TemplateManifest:
    logo = DecorElement(
        layout_ids=["M01"], x=11 * 360_000, y=6 * 360_000, cx=360_000, cy=180_000
    )
    return manifest.model_copy(update={"decor": Decor(logo=logo)})


def test_decor_moved_catches_a_block_over_the_logo(manifest: TemplateManifest) -> None:
    """Сдвинуть логотип из IR нельзя — его можно только накрыть своим блоком."""
    colony = deck(slide(body("Поверх логотипа", box=(10.5, 5.8, 3, 1))))
    findings = list(decor_moved(context_for("template.decor_moved", colony, _with_logo(manifest))))
    assert [f.block_id for f in findings] == ["b2"]


def test_decor_moved_ignores_a_block_anchored_in_a_placeholder(
    manifest: TemplateManifest,
) -> None:
    """Плейсхолдер, наложенный на декор, — так нарисован сам шаблон.

    Замер тимлида: 73 находки `decor_moved`, на наших блоках — ноль.
    Логотип помещён туда же, где лежит плейсхолдер тела макета `L07`.
    """
    body_placeholder = manifest.layout("L07").placeholders[1]
    logo = DecorElement(
        layout_ids=["M01"],
        x=body_placeholder.x,
        y=body_placeholder.y,
        cx=360_000,
        cy=180_000,
    )
    with_logo = manifest.model_copy(update={"decor": Decor(logo=logo)})
    colony = deck(slide(title(), body("Текст в плейсхолдере")))
    assert list(decor_moved(context_for("template.decor_moved", colony, with_logo))) == []


def test_decor_moved_silent_when_logo_is_free(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("В стороне", box=(2, 2, 3, 1))))
    context = context_for("template.decor_moved", colony, _with_logo(manifest))
    assert list(decor_moved(context)) == []


def test_contrast_below_wcag_catches_pale_text(manifest: TemplateManifest) -> None:
    """`lt2` — почти белый: на светлом фоне такой текст не читается."""
    colony = deck(slide(body("Бледный текст", color_ref=ColorRef.LT2)))
    findings = list(
        contrast_below_wcag(context_for("template.contrast_below_wcag", colony, manifest))
    )
    assert len(findings) == 1
    assert float(findings[0].evidence["ratio"]) < 4.5


def test_contrast_below_wcag_silent_on_dark_text(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Обычный текст", color_ref=ColorRef.DK1)))
    context = context_for("template.contrast_below_wcag", colony, manifest)
    assert list(contrast_below_wcag(context)) == []


def test_contrast_finding_admits_that_background_is_assumed(
    manifest: TemplateManifest,
) -> None:
    """Фона макета в манифесте пока нет, и находка обязана про это сказать."""
    colony = deck(slide(body("Бледный текст", color_ref=ColorRef.LT2)))
    finding = next(
        iter(contrast_below_wcag(context_for("template.contrast_below_wcag", colony, manifest)))
    )
    assert "фон макета" in finding.evidence["background_source"]


def test_typography_step_helper_is_used_when_block_has_no_own_size(
    manifest: TemplateManifest,
) -> None:
    """Кегль берётся из шкалы шаблона по роли, если в блоке он не задан."""
    step = manifest.typography(TextRole.TITLE)
    assert isinstance(step, TypographyStep)
    colony = deck(slide(title(color_ref=ColorRef.LT2)))
    findings = list(
        contrast_below_wcag(context_for("template.contrast_below_wcag", colony, manifest))
    )
    # 40 pt — крупный текст, порог мягче, но почти белое на белом не проходит и его.
    assert len(findings) == 1
