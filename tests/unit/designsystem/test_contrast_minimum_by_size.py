"""Минимум контраста — по кеглю, запас — по роли. Change `contrast-minimum-by-size`.

После `one-contrast-rule` (#146) аудит считал минимум подписи по кеглю, а страница
дизайн-системы — по роли: подпись 18 pt на странице требовала 4,5, в аудите — 3,0.
Правило переехало в слой, и оба потребителя обязаны давать один ответ.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.contrast import (
    COMFORT_CAPTION,
    MIN_BODY,
    MIN_GRAPHICS,
    MIN_LARGE,
    TextClass,
    comfort_ratio,
    readability,
    required_ratio,
    text_classes,
)
from deckforge.designsystem.models import SynthElement
from deckforge.designsystem.synth import _readable_elements
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import TemplateManifest

WHITE = "#FFFFFF"
#: Серый на белом — 3,54: выше минимума крупного текста, ниже минимума мелкого.
MID_GREY = "#888888"


@pytest.mark.parametrize(
    ("size_pt", "bold", "expected"),
    [
        (None, False, MIN_BODY),
        (12.0, False, MIN_BODY),
        (18.0, False, MIN_LARGE),
        (14.0, True, MIN_LARGE),
        (13.0, True, MIN_BODY),
    ],
)
def test_the_minimum_of_a_caption_follows_its_size(
    size_pt: float | None, bold: bool, expected: float
) -> None:
    assert required_ratio(TextClass.CAPTION, size_pt=size_pt, bold=bold) == expected


def test_graphics_keep_their_own_minimum_whatever_the_size() -> None:
    assert required_ratio(TextClass.GRAPHICS, size_pt=40.0) == MIN_GRAPHICS


def test_a_large_caption_keeps_its_comfort_margin() -> None:
    """Крупный кегль снимает с подписи минимум мелкого текста, но не её запас."""
    verdict = readability(MID_GREY, WHITE, TextClass.CAPTION, size_pt=18.0)

    assert verdict.required == MIN_LARGE
    assert verdict.comfort == COMFORT_CAPTION
    assert verdict.passes, "3,54 проходит минимум крупного текста"
    assert verdict.tight, "но запаса подписи в нём нет"


def test_only_a_caption_has_comfort_above_its_minimum() -> None:
    verdict = readability(MID_GREY, WHITE, TextClass.BODY, size_pt=18.0)

    assert verdict.required == verdict.comfort == MIN_LARGE
    assert not verdict.tight


def test_the_classes_split_the_minimum_from_the_margin() -> None:
    assert text_classes(18.0, role=TextRole.CAPTION) == (TextClass.LARGE, TextClass.CAPTION)
    assert text_classes(12.0, role=TextRole.CAPTION) == (TextClass.BODY, TextClass.CAPTION)
    assert text_classes(24.0, role=TextRole.TITLE) == (TextClass.LARGE, TextClass.LARGE)


@pytest.mark.parametrize("role", [TextRole.CAPTION, TextRole.BODY, TextRole.TITLE, None])
@pytest.mark.parametrize("bold", [False, True])
@pytest.mark.parametrize("size_pt", [9.0, 12.0, 14.0, 16.0, 18.0, 24.0])
def test_the_page_and_the_audit_ask_the_same_minimum_and_margin(
    size_pt: float, bold: bool, role: TextRole | None
) -> None:
    """Одно правило — два потребителя.

    Аудит берёт минимум у класса без роли и запас у класса с ролью
    (`audit.template.block_text_classes`). Страница спрашивает `readability`
    с классом по роли и кеглем элемента. Числа обязаны совпасть на любой комбинации.
    """
    minimum_kind, margin_kind = text_classes(size_pt, bold=bold, role=role)
    page = readability(MID_GREY, WHITE, margin_kind, size_pt=size_pt, bold=bold)

    assert page.required == required_ratio(minimum_kind)
    assert page.comfort == max(comfort_ratio(margin_kind), page.required)


def test_the_design_system_page_asks_a_large_caption_for_the_large_minimum(
    manifest: TemplateManifest,
) -> None:
    """Ровно тот случай, из-за которого change: подпись шаблона набрана 18 pt.

    До правки страница писала «при нужных 4.5» и требовала от подписи минимум
    мелкого текста, хотя аудит колоды спрашивал с того же текста 3,0.
    """
    scale = [
        step.model_copy(update={"size_pt": 18.0}) if step.role is TextRole.CAPTION else step
        for step in manifest.typography_scale
    ]
    colors = manifest.theme.colors.model_copy(update={"accent1": MID_GREY, "lt1": WHITE})
    large_captions = manifest.model_copy(
        update={
            "typography_scale": scale,
            "theme": manifest.theme.model_copy(update={"colors": colors}),
        }
    )
    label = SynthElement(
        group="плашки",
        kind="section_label",
        title="Метка раздела",
        text="РАЗДЕЛ",
        size_pt=18.0,
        color_ref=ColorRef.ACCENT1,
        on_color_ref=ColorRef.LT1,
    )

    fixed, defects = _readable_elements(large_captions, derive(large_captions), [label])

    assert not any(defect.required == MIN_BODY for defect in defects)
    note = fixed[0].note
    assert "при нужных 3.0" in note, note
    assert "при нужных 4.5" not in note
