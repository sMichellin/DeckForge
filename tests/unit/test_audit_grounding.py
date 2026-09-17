"""`content.numbers_grounded`: сверка чисел слайда с контент-пакетом. Change (18)."""

from __future__ import annotations

import pytest

from deckforge.audit.registry import CheckUnavailable
from deckforge.audit.semantic.grounding import numbers_grounded
from deckforge.domain.content import Brief, ContentPackage, Fact, Number
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide, title


def _content(*numbers: tuple[float, str | None]) -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="report", audience="правление", target_slides=12),
        facts=[
            Fact(
                fact_id=f"f{index:03d}",
                text="Выручка выросла",
                numbers=[Number(value=value, unit=unit, raw=f"{value:g}")],
            )
            for index, (value, unit) in enumerate(numbers, start=1)
        ],
    )


def test_catches_a_number_that_is_not_in_the_materials(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("Выручка выросла на 42 % за квартал")))
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((37.0, "%"))
    )
    findings = list(numbers_grounded(context))
    assert len(findings) == 1
    assert findings[0].evidence["value"] == "42"


def test_silent_when_the_number_came_from_the_materials(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("Выручка выросла на 37 % за квартал")))
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((37.0, "%"))
    )
    assert list(numbers_grounded(context)) == []


def test_percent_and_fraction_are_the_same_number(manifest: TemplateManifest) -> None:
    """«37 %» на слайде и 0.37 в источнике — одно число в разных единицах, не находка."""
    colony = deck(slide(title(), body("Доля канала — 37 %")))
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((0.37, None))
    )
    assert list(numbers_grounded(context)) == []


def test_rounding_on_the_slide_is_not_a_finding(manifest: TemplateManifest) -> None:
    """На слайде округляют: 37,5 % превращается в 38 %."""
    colony = deck(slide(title(), body("Рост составил 38 %")))
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((37.5, "%"))
    )
    assert list(numbers_grounded(context)) == []


def test_unavailable_without_content(manifest: TemplateManifest) -> None:
    """Контент-пакета нет — сверять не с чем; это пропуск, а не «все числа на месте»."""
    colony = deck(slide(title(), body("Выручка выросла на 42 %")))
    with pytest.raises(CheckUnavailable):
        list(numbers_grounded(context_for("content.numbers_grounded", colony, manifest)))


def test_unavailable_for_an_unsupported_language(manifest: TemplateManifest) -> None:
    """Разбор чисел пока только для русского. Непроверенные числа — не проверенные."""
    colony = deck(slide(title(), body("Revenue grew by 42 percent")))
    english = colony.model_copy(update={"language": "en"})
    context = context_for(
        "content.numbers_grounded", english, manifest, content=_content((37.0, "%"))
    )
    with pytest.raises(CheckUnavailable):
        list(numbers_grounded(context))
