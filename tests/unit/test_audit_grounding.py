"""`content.numbers_grounded`: сверка чисел слайда с контент-пакетом. Change (18)."""

from __future__ import annotations

import pytest

from deckforge.audit.registry import CheckUnavailable
from deckforge.audit.semantic.grounding import numbers_grounded
from deckforge.domain.content import Brief, ContentPackage, Fact, Number
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, bullets, context_for, deck, slide, title


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


# ------------------------------------------- счёт пунктов — не выдуманное число (A10)


def test_a_count_of_items_on_the_slide_is_not_invented(manifest: TemplateManifest) -> None:
    """A10, прогон aa5eca9aa135 s08: «4» на слайде, где под заголовком четыре пункта.

    Это не выдуманная цифра, а счёт того, что на слайде и так видно. Запретить его
    значит запретить заголовок «Четыре шага внедрения».
    """
    colony = deck(
        slide(
            title("4 шага внедрения"),
            bullets("Разобрать шаблон", "Понять контент", "Подобрать паттерн", "Сверстать"),
        )
    )
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((37.0, "%"))
    )

    assert list(numbers_grounded(context)) == []


def test_a_count_that_does_not_match_is_still_a_finding(manifest: TemplateManifest) -> None:
    """Норма к тому же правилу: «4 шага» над тремя пунктами — по-прежнему находка.

    Разрешён счёт, а не любое маленькое число.
    """
    colony = deck(
        slide(title("4 шага внедрения"), bullets("Разобрать", "Понять", "Сверстать"))
    )
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((37.0, "%"))
    )
    findings = list(numbers_grounded(context))

    assert len(findings) == 1 and findings[0].evidence["value"] == "4"


def test_a_measurement_is_never_excused_by_a_count(manifest: TemplateManifest) -> None:
    """Норма: единица измерения снимает вопрос. «4 %» над четырьмя пунктами — находка.

    Иначе правило открывало бы дорогу выдуманным показателям на любом слайде,
    где столько же пунктов.
    """
    colony = deck(
        slide(
            title("Рост на 4 %"),
            bullets("Первый", "Второй", "Третий", "Четвёртый"),
        )
    )
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((37.0, "%"))
    )
    findings = list(numbers_grounded(context))

    assert len(findings) == 1 and findings[0].evidence["unit"] == "%"


def test_one_is_not_a_count(manifest: TemplateManifest) -> None:
    """Норма: «1» попадается в тексте на каждом шагу и счётом не считается."""
    colony = deck(slide(title("1 вывод из отчёта"), bullets("Единственный пункт")))
    context = context_for(
        "content.numbers_grounded", colony, manifest, content=_content((37.0, "%"))
    )

    assert [f.evidence["value"] for f in numbers_grounded(context)] == ["1"]
