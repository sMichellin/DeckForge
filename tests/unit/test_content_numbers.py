"""Извлечение чисел из русского текста. Change (7) `content-ingestion`.

Формы записи взяты не из головы: это то, что реально приходит из `.docx` и `.pdf`
после markitdown — с неразрывными пробелами, типографским минусом и двойными
пробелами внутри предложения (см. proposal.md, раздел Explore).
"""

from __future__ import annotations

import pytest

from deckforge.domain.content import Number
from deckforge.parsing.content import extract_numbers

NBSP = " "
NARROW = " "
MINUS = "−"


def only(text: str) -> Number:
    numbers = extract_numbers(text)
    assert len(numbers) == 1, f"ожидалось одно число, получено {numbers}"
    return numbers[0]


@pytest.mark.parametrize(
    ("text", "value", "unit", "raw"),
    [
        ("рост 37,5 %", 37.5, "%", "37,5 %"),
        ("рост 37,5%", 37.5, "%", "37,5%"),
        (f"доля 68{NBSP}%", 68.0, "%", f"68{NBSP}%"),
        ("после PDF 68  % опрошенных", 68.0, "%", "68  %"),
        (f"выручка 1{NBSP}200{NBSP}млн{NBSP}₽", 1200.0, "млн ₽", f"1{NBSP}200{NBSP}млн{NBSP}₽"),
        ("выручка 1 200 млн ₽", 1200.0, "млн ₽", "1 200 млн ₽"),
        ("объём 48,3 млрд ₽", 48.3, "млрд ₽", "48,3 млрд ₽"),
        ("бюджет 24 млн руб.", 24.0, "млн руб", "24 млн руб."),
        ("рост x2.3", 2.3, "x", "x2.3"),
        ("рост х2,3 за год", 2.3, "x", "х2,3"),
        ("вырос в 2,5 раза", 2.5, "x", "в 2,5 раза"),
        ("дешевле в 1,8 раза", 1.8, "x", "в 1,8 раза"),
        (f"отток {MINUS}12 п.{NARROW}п.", -12.0, "п.п.", f"{MINUS}12 п.{NARROW}п."),
        ("отток -12 п.п.", -12.0, "п.п.", "-12 п.п."),
        ("снижение -5 %", -5.0, "%", "-5 %"),
        ("доступность 99,95 %", 99.95, "%", "99,95 %"),
        ("доля 0,87 от общей", 0.87, None, "0,87"),
        ("выборка 412 организаций", 412.0, None, "412"),
    ],
)
def test_russian_number_forms(text: str, value: float, unit: str | None, raw: str) -> None:
    number = only(text)
    assert number.value == pytest.approx(value)
    assert number.unit == unit
    assert number.raw == raw, "исходное написание обязано сохраняться символ в символ"


@pytest.mark.parametrize(
    "text",
    [
        "плановый рост на 2027 год",
        "запущена в 2024 году",
        "поддержка 24/7",
        "текущая версия v2.1",
        "версия v 3 вышла",
        "документ от 12.09.2026",
        "сбой начался в 14:32",
        "восстановление завершено в 15:07:30",
    ],
)
def test_years_versions_dates_times_and_modes_are_not_measurements(text: str) -> None:
    """Иначе аудит будет добросовестно искать в источнике «число 2027»."""
    assert extract_numbers(text) == []


def test_range_gives_both_edges_and_keeps_one_raw() -> None:
    low, high = extract_numbers("целевой рост 15–20 %")
    assert (low.value, high.value) == (15.0, 20.0)
    assert low.unit == high.unit == "%"
    assert low.raw == high.raw == "15–20 %"


def test_year_inside_sentence_does_not_swallow_the_real_number() -> None:
    numbers = extract_numbers("в 2025 году выручка составила 872 млн ₽")
    assert [(n.value, n.unit) for n in numbers] == [(872.0, "млн ₽")]


def test_several_numbers_keep_source_order() -> None:
    numbers = extract_numbers("сократили с 12 до 7 минут")
    assert [n.value for n in numbers] == [12.0, 7.0]


def test_mixed_sentence_from_the_synthetic_pack() -> None:
    text = (
        f"Выручка выросла на 37,5{NBSP}% и достигла 1{NBSP}200{NBSP}млн{NBSP}₽, "
        f"отток снизился на {MINUS}12{NBSP}п.{NARROW}п."
    )
    assert [(n.value, n.unit) for n in extract_numbers(text)] == [
        (37.5, "%"),
        (1200.0, "млн ₽"),
        (-12.0, "п.п."),
    ]


def test_unsupported_language_is_refused_loudly() -> None:
    with pytest.raises(ValueError, match="только для русского"):
        extract_numbers("growth of 37.5 percent", language="en")
