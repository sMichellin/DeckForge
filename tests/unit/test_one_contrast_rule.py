"""Один свод правил о контрасте: аудит и писатель берут порог у `designsystem.contrast`.

Change `one-contrast-rule` (DG1). На каждый класс текста — нарушитель и норма
(правило 7). Фон — слот темы синтетического манифеста, а не цвет конкретного шаблона:
порог выбирается по классу, и числа в тестах — свойства этой синтетической темы.

Шкала синтетического манифеста: заголовок 40 pt полужирный, тело 18 pt, подпись 12 pt.
Тело 18 pt — это уже крупный текст по правилу слоя, поэтому для класса «обычный»
блок набирается 14 pt явно.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.audit.deterministic.template import (
    block_text_classes,
    contrast_below_wcag,
    contrast_thresholds,
)
from deckforge.audit.findings import make_finding
from deckforge.designsystem.contrast import (
    COMFORT_CAPTION,
    MIN_BODY,
    MIN_GRAPHICS,
    MIN_LARGE,
    TextClass,
)
from deckforge.domain.enums import ColorRef, Severity, TextRole
from deckforge.domain.rules import contrast_ratio
from deckforge.domain.template import LayoutBackground, TemplateManifest, ThemeColors
from deckforge.rendering.writer import PptxWriter
from tests.unit._audit_builders import body, context_for, deck, slide, title

CHECK = "template.contrast_below_wcag"


def _on(manifest: TemplateManifest, ref: ColorRef) -> TemplateManifest:
    """Все макеты залиты слотом темы `ref`."""
    background = LayoutBackground(
        color_hex=manifest.theme.colors.get(ref), color_ref=ref, source="layout"
    )
    layouts = [
        layout.model_copy(update={"background": background}) for layout in manifest.layouts
    ]
    return manifest.model_copy(update={"layouts": layouts})


def _ratio(manifest: TemplateManifest, text: ColorRef, ground: ColorRef) -> float:
    colors = manifest.theme.colors
    return contrast_ratio(colors.get(text), colors.get(ground))


def _findings(manifest: TemplateManifest, *blocks: object, **overrides: float) -> list:
    colony = deck(slide(*blocks))  # type: ignore[arg-type]
    return list(contrast_below_wcag(context_for(CHECK, colony, manifest, **overrides)))


# --- конфиг и слой -----------------------------------------------------------


def test_config_names_three_minimums_and_the_layer_picks_the_class(
    manifest: TemplateManifest,
) -> None:
    """В YAML три значения, по одному на порог; одного на всю колоду больше нет."""
    colony = deck(slide(body()))
    thresholds = contrast_thresholds(context_for(CHECK, colony, manifest))
    assert thresholds == {
        TextClass.BODY: MIN_BODY,
        TextClass.CAPTION: MIN_BODY,
        TextClass.LARGE: MIN_LARGE,
        TextClass.GRAPHICS: MIN_GRAPHICS,
    }


def test_missing_param_falls_back_to_the_layer_not_to_an_own_number(
    manifest: TemplateManifest,
) -> None:
    from deckforge.audit.context import AuditContext

    context = AuditContext(manifest=manifest, deck=deck(slide(body())), params={})
    assert contrast_thresholds(context)[TextClass.LARGE] == MIN_LARGE
    assert contrast_thresholds(context)[TextClass.BODY] == MIN_BODY


def test_param_overrides_the_value_for_its_class(manifest: TemplateManifest) -> None:
    colony = deck(slide(body()))
    context = context_for(CHECK, colony, manifest, graphics=3.5, large=3.2)
    thresholds = contrast_thresholds(context)
    assert thresholds[TextClass.GRAPHICS] == 3.5
    assert thresholds[TextClass.LARGE] == 3.2
    assert thresholds[TextClass.BODY] == MIN_BODY


def test_text_class_comes_from_size_and_the_template_weight(manifest: TemplateManifest) -> None:
    """Кегль — блока или шкалы; полужирный — у ступени шаблона, в IR его нет.

    Первый ответ — чей минимум (кегль и начертание), второй — чей запас (роль).
    """
    assert block_text_classes(body(size_pt=14), manifest) == (TextClass.BODY, TextClass.BODY)
    assert block_text_classes(body(), manifest)[0] is TextClass.LARGE  # 18 pt по шкале
    assert block_text_classes(title(size_pt=14), manifest)[0] is TextClass.LARGE  # полужирный
    assert block_text_classes(body(size_pt=14, role=TextRole.CAPTION), manifest) == (
        TextClass.BODY,
        TextClass.CAPTION,
    )


# --- обычный текст: минимум 4,5 ---------------------------------------------


def test_body_text_below_the_minimum_is_an_error(manifest: TemplateManifest) -> None:
    light = _on(manifest, ColorRef.LT1)
    assert _ratio(manifest, ColorRef.ACCENT6, ColorRef.LT1) < MIN_BODY
    findings = _findings(light, body(color_ref=ColorRef.ACCENT6, size_pt=14))
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].evidence["text_class"] == "body"
    assert findings[0].evidence["required"] == "4.5"


def test_body_text_above_the_minimum_is_silent(manifest: TemplateManifest) -> None:
    light = _on(manifest, ColorRef.LT1)
    assert MIN_BODY <= _ratio(manifest, ColorRef.ACCENT1, ColorRef.LT1) < COMFORT_CAPTION
    assert _findings(light, body(color_ref=ColorRef.ACCENT1, size_pt=14)) == []


def test_raised_body_param_turns_the_same_pair_into_an_error(
    manifest: TemplateManifest,
) -> None:
    """Порог действительно берётся из конфига, а не из тела проверки."""
    light = _on(manifest, ColorRef.LT1)
    findings = _findings(light, body(color_ref=ColorRef.ACCENT1, size_pt=14), body=5.0)
    assert [f.severity for f in findings] == [Severity.ERROR]


# --- крупный текст: минимум 3,0 ---------------------------------------------


def test_bold_text_from_14_pt_is_large_and_passes_at_three(manifest: TemplateManifest) -> None:
    """Раньше крупным считался только кегль от 18 pt, и 14 pt полужирным требовали 4,5.

    Правило слоя — «от 18 pt или от 14 pt полужирным»: заголовок шкалы полужирный,
    поэтому 14 pt заголовка — крупный текст с порогом 3,0.
    """
    light = _on(manifest, ColorRef.LT1)
    assert MIN_LARGE <= _ratio(manifest, ColorRef.ACCENT6, ColorRef.LT1) < MIN_BODY
    assert _findings(light, title(color_ref=ColorRef.ACCENT6, size_pt=14)) == []


def test_large_text_below_three_is_an_error(manifest: TemplateManifest) -> None:
    light = _on(manifest, ColorRef.LT1)
    assert _ratio(manifest, ColorRef.ACCENT2, ColorRef.LT1) < MIN_LARGE
    findings = _findings(light, title(color_ref=ColorRef.ACCENT2, size_pt=14))
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].evidence["text_class"] == "large"
    assert findings[0].evidence["required"] == "3.0"


# --- подпись: минимум 4,5, комфорт 7,0 --------------------------------------


def _caption(ref: ColorRef) -> object:
    return body("Источник: отчёт за квартал", role=TextRole.CAPTION, color_ref=ref)


def test_caption_without_margin_is_info_not_error(manifest: TemplateManifest) -> None:
    """Минимум взят, запаса нет: замечание, а не ошибка на каждом слайде."""
    light = _on(manifest, ColorRef.LT1)
    ratio = _ratio(manifest, ColorRef.ACCENT1, ColorRef.LT1)
    assert MIN_BODY <= ratio < COMFORT_CAPTION
    findings = _findings(light, _caption(ColorRef.ACCENT1))
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO
    assert findings[0].evidence["text_class"] == "caption"
    assert findings[0].evidence["comfort"] == "7.0"


def test_caption_with_margin_is_silent(manifest: TemplateManifest) -> None:
    light = _on(manifest, ColorRef.LT1)
    assert _ratio(manifest, ColorRef.DK2, ColorRef.LT1) >= COMFORT_CAPTION
    assert _findings(light, _caption(ColorRef.DK2)) == []


def test_caption_below_the_minimum_is_still_an_error(manifest: TemplateManifest) -> None:
    light = _on(manifest, ColorRef.LT1)
    assert _ratio(manifest, ColorRef.ACCENT6, ColorRef.LT1) < MIN_BODY
    findings = _findings(light, _caption(ColorRef.ACCENT6))
    assert [f.severity for f in findings] == [Severity.ERROR]


def test_large_caption_takes_the_large_minimum_and_is_only_info(
    manifest: TemplateManifest,
) -> None:
    """Подпись 18 pt — крупный текст: минимум 3,0, а не 4,5 (требование change).

    Роль вперёд кегля превратила бы такую подпись в ошибку при 3,1 — у шаблона, где
    подпись набрана 18 pt, это ошибка на каждом слайде с подписью. Роль даёт только
    замечание о запасе.
    """
    light = _on(manifest, ColorRef.LT1)
    ratio = _ratio(manifest, ColorRef.ACCENT6, ColorRef.LT1)
    assert MIN_LARGE <= ratio < MIN_BODY
    caption = body("Подпись", role=TextRole.CAPTION, color_ref=ColorRef.ACCENT6, size_pt=18)
    findings = _findings(light, caption)
    assert [f.severity for f in findings] == [Severity.INFO]
    assert findings[0].evidence["minimum_class"] == "large"
    assert findings[0].evidence["required"] == "3.0"


def test_large_caption_below_three_is_an_error(manifest: TemplateManifest) -> None:
    light = _on(manifest, ColorRef.LT1)
    assert _ratio(manifest, ColorRef.ACCENT2, ColorRef.LT1) < MIN_LARGE
    caption = body("Подпись", role=TextRole.CAPTION, color_ref=ColorRef.ACCENT2, size_pt=18)
    assert [f.severity for f in _findings(light, caption)] == [Severity.ERROR]


def test_tight_and_failing_caption_get_different_ids(manifest: TemplateManifest) -> None:
    """Интерфейс помнит отклонённое по `finding_id`: замечание не должно им прятать ошибку."""
    light = _on(manifest, ColorRef.LT1)
    tight = _findings(light, _caption(ColorRef.ACCENT1))[0]
    failing = _findings(light, _caption(ColorRef.ACCENT6))[0]
    assert tight.finding_id != failing.finding_id


# --- уровень находки ----------------------------------------------------------


def test_finding_can_be_softer_than_declared_but_never_stricter() -> None:
    soft = make_finding(check_id=CHECK, message="м", severity=Severity.INFO)
    assert soft.severity is Severity.INFO
    declared = make_finding(check_id=CHECK, message="м")
    assert declared.severity is Severity.ERROR
    capped = make_finding(
        check_id="density.too_many_bullets", message="м", severity=Severity.ERROR
    )
    assert capped.severity is Severity.WARNING


# --- писатель: тот же свод правил --------------------------------------------


def _writer(manifest: TemplateManifest) -> PptxWriter:
    return PptxWriter(Path("не-открывается.pptx"), manifest)


def test_writer_picks_free_text_colour_by_the_layer_rule(manifest: TemplateManifest) -> None:
    """Выбранный цвет берёт порог класса «обычный текст» на фоне макета."""
    for ground in (ColorRef.DK1, ColorRef.LT1, ColorRef.ACCENT1):
        painted = _on(manifest, ground)
        chosen = _writer(painted)._readable_on_background(slide())
        assert chosen is not None
        assert _ratio(manifest, chosen, ground) >= MIN_BODY


def test_writer_keeps_the_best_slot_when_no_slot_passes(manifest: TemplateManifest) -> None:
    """Порог не берёт ни один слот — дефект шаблона; чёрный по умолчанию был бы хуже."""
    grey = manifest.theme.model_copy(
        update={
            "colors": ThemeColors(
                **{
                    **manifest.theme.colors.model_dump(by_alias=True),
                    "dk1": "#5A5A5A",
                    "lt1": "#A0A0A0",
                    "dk2": "#666666",
                    "lt2": "#999999",
                }
            )
        }
    )
    dull = manifest.model_copy(update={"theme": grey})
    background = LayoutBackground(color_hex="#808080", source="layout")
    dull = dull.model_copy(
        update={
            "layouts": [
                layout.model_copy(update={"background": background}) for layout in dull.layouts
            ]
        }
    )
    chosen = _writer(dull)._readable_on_background(slide())
    assert chosen is not None
    best = max(
        (ColorRef.DK1, ColorRef.LT1, ColorRef.DK2, ColorRef.LT2),
        key=lambda ref: contrast_ratio(grey.colors.get(ref), "#808080"),
    )
    assert chosen is best
    assert contrast_ratio(grey.colors.get(chosen), "#808080") < MIN_BODY


def test_writer_leaves_colour_to_the_scale_without_a_background(
    manifest: TemplateManifest,
) -> None:
    assert _writer(manifest)._readable_on_background(slide()) is None


@pytest.mark.parametrize("ground", [ColorRef.DK1, ColorRef.LT1])
def test_writer_colour_passes_the_audit_it_would_be_checked_by(
    manifest: TemplateManifest, ground: ColorRef
) -> None:
    """Один свод правил: цвет, выбранный писателем, аудит не называет нарушением."""
    painted = _on(manifest, ground)
    chosen = _writer(painted)._readable_on_background(slide())
    assert chosen is not None
    assert _findings(painted, body(color_ref=chosen, size_pt=14)) == []
