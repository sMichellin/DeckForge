"""Пороги контраста по роли текста. Change `a-minimum-is-not-a-norm`.

Правила заказчика из «Правила контраста. Пример Figma»: порог зависит от кегля
и начертания, мелкому служебному тексту нужен запас, а «прошло впритык» не выдаётся
за норму. Числа в тестах взяты готовыми парами серого на белом, а не пересчитаны
тем же способом, что и код: 4,54 — минимум рабочего текста, 3,03 — минимум крупного,
7,0 — запас подписи.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.contrast import (
    COMFORT_CAPTION,
    MIN_BODY,
    MIN_LARGE,
    TextClass,
    deeper_plate,
    ink_on_plate,
    readability,
    readable_ref,
    text_class,
)
from deckforge.designsystem.synth import paints_with_ink
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import TemplateManifest, Theme, ThemeColors
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template

WHITE = "#FFFFFF"
BODY_EDGE = "#767676"  # 4,54 на белом
LARGE_EDGE = "#949494"  # 3,03 на белом
CAPTION_SAFE = "#595959"  # 7,0 на белом

ACCENT_REFS = [
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
]

CASE_TEMPLATES = [
    "VK Tech шаблон.pptx",
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
    "Шаблон презентации VK Education.pptx",
]


def recoloured(manifest: TemplateManifest, **slots: str) -> TemplateManifest:
    colors: ThemeColors = manifest.theme.colors.model_copy(update=slots)
    theme: Theme = manifest.theme.model_copy(update={"colors": colors})
    return manifest.model_copy(update={"theme": theme})


# --- класс текста --------------------------------------------------------------


@pytest.mark.parametrize(
    ("size_pt", "bold", "expected"),
    [
        (18.0, False, TextClass.LARGE),
        (17.9, False, TextClass.BODY),
        (14.0, True, TextClass.LARGE),
        (14.0, False, TextClass.BODY),
        (13.9, True, TextClass.BODY),
    ],
)
def test_the_class_of_the_text_comes_from_its_size_and_weight(
    size_pt: float, bold: bool, expected: TextClass
) -> None:
    """«От 24 px Regular или от 19 px Bold» — это 18 pt и 14 pt.

    Граница проверяется с обеих сторон: 17,9 pt уже не крупный, 13,9 полужирного тоже.
    """
    assert text_class(size_pt, bold=bold) is expected


def test_the_caption_role_of_the_template_is_a_caption_at_any_size() -> None:
    """Роль решает раньше кегля: подпись остаётся подписью, даже набранная крупно."""
    assert text_class(24.0, role=TextRole.CAPTION) is TextClass.CAPTION


# --- пороги --------------------------------------------------------------------


def test_a_pair_at_the_minimum_passes_for_a_paragraph_and_is_tight_for_a_caption() -> None:
    """Нарушитель и норма в одной паре: 4,54 — норма абзацу и «впритык» подписи."""
    body = readability(BODY_EDGE, WHITE, TextClass.BODY)
    caption = readability(BODY_EDGE, WHITE, TextClass.CAPTION)

    assert body.passes and not body.tight
    assert caption.passes, "минимум подписи тот же, что у абзаца"
    assert caption.tight, "запаса нет — вот это и обязано быть видно"
    assert (body.required, caption.comfort) == (MIN_BODY, COMFORT_CAPTION)


def test_a_pair_with_a_margin_is_not_tight_for_a_caption() -> None:
    caption = readability(CAPTION_SAFE, WHITE, TextClass.CAPTION)

    assert caption.passes and not caption.tight


def test_a_pair_for_large_text_passes_where_a_paragraph_fails() -> None:
    """3,03 — крупному хватает, рабочему тексту нет. Порог один на класс, а не на страницу."""
    assert readability(LARGE_EDGE, WHITE, TextClass.LARGE).passes
    assert not readability(LARGE_EDGE, WHITE, TextClass.BODY).passes
    assert readability(LARGE_EDGE, WHITE, TextClass.GRAPHICS).passes
    assert readability(LARGE_EDGE, WHITE, TextClass.LARGE).required == MIN_LARGE


# --- подбор слота --------------------------------------------------------------


def test_the_ink_keeps_the_hue_of_the_template_and_gains_the_contrast(
    manifest: TemplateManifest,
) -> None:
    """«Для мелкого текста использовать глубокий синий» — не чёрный: тон остаётся."""
    blue = recoloured(manifest, accent1="#4D94FF", accent2="#003D99", dk1="#101014")

    chosen = readable_ref(blue.theme, WHITE, TextClass.CAPTION, prefer_hex="#4D94FF")

    assert chosen is ColorRef.ACCENT2, "ближайший по цвету из прошедших, а не самый тёмный"


def test_a_theme_that_reads_nowhere_gets_no_slot_at_all(manifest: TemplateManifest) -> None:
    """Нарушитель: шаблон из одних полутонов. Лучший из плохих не подставляется."""
    flat = recoloured(manifest, **{ref.value: "#8A8A8A" for ref in ColorRef})

    assert readable_ref(flat.theme, "#8A8A8A", TextClass.BODY) is None


# --- в структуре ---------------------------------------------------------------


def test_an_element_keeps_the_slot_of_the_template_and_names_the_one_it_was_drawn_with(
    manifest: TemplateManifest,
) -> None:
    """Подмена не стирает объявление: страница показывает и обещание, и правду."""
    weak = recoloured(manifest, accent1="#9AB8F5", lt1=WHITE, dk1="#101014")
    drawn = [item for item in derive(weak).synthesized if item.note]

    assert drawn, "акцент, не берущий свой порог, обязан быть подменён"
    item = drawn[0]
    assert item.color_ref is not None, "объявление шаблона осталось"
    assert item.shown_ref is not None and item.shown_ref is not item.color_ref
    assert item.color_ref.value in item.note and item.shown_ref.value in item.note


def test_a_template_where_nothing_reads_lists_its_defects(manifest: TemplateManifest) -> None:
    """Место без читаемой пары названо числом — на разборе шаблона, а не на презентации."""
    flat = recoloured(manifest, **{ref.value: "#8A8A8A" for ref in ColorRef})

    defects = derive(flat).contrast_defects

    assert defects, "шаблон из одних полутонов обязан дать дефекты"
    first = defects[0]
    assert first.where and first.text_class
    assert first.required >= MIN_LARGE
    assert first.best_ratio < first.required, "лучшее в теме не дотягивает — потому и дефект"


def test_a_normal_template_lists_no_defects(manifest: TemplateManifest) -> None:
    """Норма к предыдущему: у темы с чёрным и белым читаемая пара есть всегда."""
    assert derive(manifest).contrast_defects == []


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_every_pair_of_a_case_template_carries_its_threshold(name: str) -> None:
    manifest = TemplateParser().parse(case_template(name), use_cache=False)
    pairs = derive(manifest).contrast_pairs

    assert pairs
    assert all(pair.required == MIN_BODY for pair in pairs)
    assert all(pair.comfort == COMFORT_CAPTION for pair in pairs)
    assert any(pair.tight for pair in pairs), f"{name}: пар «впритык» нет — порог не считается"
    assert all(pair.ratio >= pair.required for pair in pairs if pair.tight)
    assert all(pair.ratio < pair.comfort for pair in pairs if pair.tight)


# --- надпись на плашке ---------------------------------------------------------


def test_a_dark_plate_takes_light_ink_and_a_light_plate_takes_dark(
    manifest: TemplateManifest,
) -> None:
    """Правило 4 документа: светлая плашка — графитовый текст, тёмная — белый.

    Полярность решается раньше контраста: на системном синем тёмная надпись формально
    берёт больше, чем светлая, и всё равно читается плохо.
    """
    theme = recoloured(manifest, lt1=WHITE, dk1="#101014").theme

    assert ink_on_plate(theme, "#101014", TextClass.BODY) is ColorRef.LT1, "тёмная — белый"
    assert ink_on_plate(theme, WHITE, TextClass.BODY) is ColorRef.DK1, "светлая — графит"


def test_a_plate_that_carries_nothing_gives_no_ink(manifest: TemplateManifest) -> None:
    """Нарушитель: на средней по яркости плашке светлая надпись не дотягивает."""
    theme = recoloured(manifest, accent1="#0077FF", lt1=WHITE, dk1="#101014").theme

    assert ink_on_plate(theme, "#0077FF", TextClass.BODY) is None
    assert ink_on_plate(theme, "#0077FF", TextClass.LARGE) is ColorRef.LT1, "крупному хватает"


def test_the_plate_goes_deeper_instead_of_the_ink_going_dark(
    manifest: TemplateManifest,
) -> None:
    """«Для мелкого текста безопаснее более тёмный синий фон» — тон тот же, светлота другая."""
    theme = recoloured(
        manifest, accent1="#0077FF", accent2="#0563C1", lt1=WHITE, dk1="#101014"
    ).theme

    deeper = deeper_plate(theme, "#0077FF", TextClass.BODY)

    assert deeper is not None
    plate, ink = deeper
    assert plate is ColorRef.ACCENT2, "взят тот же синий глубже, а не другой цвет"
    assert ink is ColorRef.LT1, "на нём белый наконец проходит"


def test_an_accent_with_no_deeper_twin_is_left_as_an_outline(
    manifest: TemplateManifest,
) -> None:
    """«Оставить мадженту только для маркера или границы» — когда заливка не работает."""
    only = recoloured(
        manifest,
        **{ref.value: "#0077FF" for ref in ACCENT_REFS},
        lt1=WHITE,
        dk1="#101014",
    )

    tags = [item for item in derive(only).synthesized if item.kind == "tag"]

    assert tags
    assert all(tag.outlined for tag in tags), "заливки нет — акцент остался границей"
    assert all("границей" in tag.note for tag in tags)


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_no_plate_of_a_case_template_carries_ink_of_the_wrong_polarity(name: str) -> None:
    """Главная проверка правила: чёрного на синем на странице больше не возникает."""
    from deckforge.domain.rules import contrast_ratio, relative_luminance

    manifest = TemplateParser().parse(case_template(name), use_cache=False)
    ds = derive(manifest)
    colors = manifest.theme.colors

    for item in ds.synthesized:
        #: Проверяются плашки: у элементов, которые рисуют себя знаком, `color_ref` —
        #: сам знак, и «плашки» у них нет.
        if paints_with_ink(item.kind) or item.outlined or item.shown_ref is None:
            continue
        if item.color_ref is None:
            continue
        plate_ref = item.plate_ref or item.color_ref
        plate, ink = colors.get(plate_ref), colors.get(item.shown_ref)
        if relative_luminance(plate) >= 0.4:
            continue
        assert relative_luminance(ink) > relative_luminance(plate), (
            f"{name}: на тёмной плашке {plate} надпись {ink} — тёмное по тёмному"
        )
        assert contrast_ratio(ink, plate) >= MIN_LARGE
