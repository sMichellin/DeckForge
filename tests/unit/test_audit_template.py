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
from deckforge.audit.registry import CheckUnavailable
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import (
    Decor,
    DecorElement,
    LayoutBackground,
    TemplateManifest,
    TypographyStep,
)
from tests.unit._audit_builders import body, chart, context_for, deck, slide, title


def test_font_not_in_theme_catches_a_third_family(manifest: TemplateManifest) -> None:
    """Порог занижен до одной гарнитуры: в колоде их две, заголовочная и текстовая."""
    colony = deck(slide(title(), body()))
    context = context_for("template.font_not_in_theme", colony, manifest, max_families=1)
    findings = list(font_not_in_theme(context))
    assert [f.evidence.get("families") for f in findings if "families" in f.evidence]


def test_font_not_in_theme_silent_within_the_limit(manifest: TemplateManifest) -> None:
    """В пределах лимита и без файла — не «чисто», а «не мерили»: гарнитуры текста видны
    только в .pptx (change `the-font-check-names-its-skip`). Норма с файлом — ниже."""
    colony = deck(slide(title(), body()))
    context = context_for("template.font_not_in_theme", colony, manifest)
    with pytest.raises(CheckUnavailable):
        list(font_not_in_theme(context))


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


def _with_background(
    manifest: TemplateManifest, background: LayoutBackground
) -> TemplateManifest:
    """Тот же манифест, но у всех макетов задан фон. Фикстура общая и правится тимлидом."""
    return manifest.model_copy(
        update={
            "layouts": [
                layout.model_copy(update={"background": background})
                for layout in manifest.layouts
            ]
        }
    )


def _dark(manifest: TemplateManifest) -> TemplateManifest:
    """Макеты залиты тёмным слотом темы — как все 15 макетов VK WorkSpace."""
    return _with_background(
        manifest,
        LayoutBackground(
            color_hex=manifest.theme.colors.get(ColorRef.DK1),
            color_ref=ColorRef.DK1,
            source="layout",
        ),
    )


def test_contrast_below_wcag_catches_pale_text(manifest: TemplateManifest) -> None:
    """`lt2` — почти белый: на светлом фоне такой текст не читается."""
    light = _with_background(
        manifest,
        LayoutBackground(
            color_hex=manifest.theme.colors.get(ColorRef.LT1),
            color_ref=ColorRef.LT1,
            source="layout",
        ),
    )
    colony = deck(slide(body("Бледный текст", color_ref=ColorRef.LT2)))
    findings = list(
        contrast_below_wcag(context_for("template.contrast_below_wcag", colony, light))
    )
    assert len(findings) == 1
    assert float(findings[0].evidence["ratio"]) < 4.5


def test_contrast_below_wcag_silent_on_dark_text(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Обычный текст", color_ref=ColorRef.DK1)))
    context = context_for("template.contrast_below_wcag", colony, manifest)
    assert list(contrast_below_wcag(context)) == []


def test_contrast_measures_the_layout_background_not_the_theme(
    manifest: TemplateManifest,
) -> None:
    """Дефект 19.09: `dk1` по `dk1`, контраст 1:1 — и вердикт «норма».

    Проверка сравнивала цвет текста со светлым слотом темы, поэтому тёмный заголовок
    на тёмном макете выглядел как 21:1. Колода из двенадцати невидимых заголовков
    получила «находок 0».
    """
    colony = deck(slide(body("Тёмный текст на тёмном фоне", color_ref=ColorRef.DK1)))
    findings = list(
        contrast_below_wcag(context_for("template.contrast_below_wcag", colony, _dark(manifest)))
    )
    assert len(findings) == 1
    assert float(findings[0].evidence["ratio"]) == pytest.approx(1.0, abs=0.01)
    assert findings[0].evidence["background"] == manifest.theme.colors.get(ColorRef.DK1)
    assert findings[0].evidence["background_source"] == "layout"


def test_contrast_silent_when_light_text_lies_on_a_dark_layout(
    manifest: TemplateManifest,
) -> None:
    """Норма к той же правке: на тёмном макете светлый текст читается и находки не даёт."""
    colony = deck(slide(body("Светлый текст на тёмном фоне", color_ref=ColorRef.LT1)))
    context = context_for("template.contrast_below_wcag", colony, _dark(manifest))
    assert list(contrast_below_wcag(context)) == []


def test_contrast_admits_when_the_manifest_has_no_background(
    manifest: TemplateManifest,
) -> None:
    """Манифест прежнего парсера фона не знает — находка обязана про это сказать."""
    colony = deck(slide(body("Бледный текст", color_ref=ColorRef.LT2)))
    finding = next(
        iter(contrast_below_wcag(context_for("template.contrast_below_wcag", colony, manifest)))
    )
    assert "без разбора фона" in finding.evidence["background_source"]


def test_contrast_says_when_the_background_is_a_picture(manifest: TemplateManifest) -> None:
    """Под текстом подложка: цвет усреднён, и вердикт назван приблизительным."""
    with_picture = _with_background(
        manifest,
        LayoutBackground(
            color_hex=manifest.theme.colors.get(ColorRef.DK1),
            source="picture",
            is_image=True,
        ),
    )
    colony = deck(slide(body("Тёмный текст", color_ref=ColorRef.DK1)))
    finding = next(
        iter(
            contrast_below_wcag(
                context_for("template.contrast_below_wcag", colony, with_picture)
            )
        )
    )
    assert "приблизителен" in finding.evidence["background_source"]


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


def test_theme_font_reference_is_not_a_foreign_family(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C10: «+mn-lt» — ссылка на шрифт темы, а не гарнитура.

    Ошибка выпадала на каждом прогоне «Шаблона 2024». Отчёт, который врёт на эталоне,
    учит себя не читать — это хуже отсутствующей проверки.
    """
    from deckforge.audit.deterministic import template as module

    monkeypatch.setattr(module, "_fonts_in_file", lambda path: {"1": ["+mn-lt"]})
    context = context_for(
        "template.font_not_in_theme", deck(slide(title())), manifest, deck_path=Path("deck.pptx")
    )
    findings = list(font_not_in_theme(context))

    assert not [f for f in findings if str(f.evidence.get("family", "")).startswith("+")]


def test_a_genuinely_foreign_family_is_still_caught(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Правило 7: у проверки два теста — на норме и на нарушителе."""
    from deckforge.audit.deterministic import template as module

    monkeypatch.setattr(module, "_fonts_in_file", lambda path: {"1": ["Comic Sans MS"]})
    context = context_for(
        "template.font_not_in_theme", deck(slide(title())), manifest, deck_path=Path("deck.pptx")
    )
    findings = list(font_not_in_theme(context))

    assert [f for f in findings if f.evidence.get("family") == "Comic Sans MS"]


def test_reference_and_its_family_are_one_font(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Иначе ссылка и сам шрифт считались двумя гарнитурами и переполняли предел."""
    from deckforge.audit.deterministic import template as module

    minor = manifest.theme.fonts.minor_latin
    monkeypatch.setattr(module, "_fonts_in_file", lambda path: {"1": ["+mn-lt", minor]})
    context = context_for(
        "template.font_not_in_theme", deck(slide(title())), manifest, deck_path=Path("deck.pptx")
    )
    families = [
        str(f.evidence.get("families", "")) for f in font_not_in_theme(context) if f.evidence
    ]

    assert not any("+mn-lt" in item for item in families)


def test_theme_font_token_resolves_to_the_theme_family(manifest: TemplateManifest) -> None:
    """Корень C10: токен — ссылка на шрифт темы, а не название гарнитуры."""
    from deckforge.rendering.theme_binding import font_family_for_token

    assert font_family_for_token("+mn-lt", manifest) == manifest.theme.fonts.minor_latin
    assert font_family_for_token("+mj-lt", manifest) == manifest.theme.fonts.major_latin
    assert font_family_for_token("Play", manifest) is None
