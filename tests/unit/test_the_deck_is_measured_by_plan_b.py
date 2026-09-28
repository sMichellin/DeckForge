"""Мерило плана Б по `run.json`. Change `the-deck-is-measured-by-plan-b`.

План Б принимается не по числу ошибок аудита, а по таблице: пример по смыслу, повторы,
снятые, сплющенные и обрезанные блоки (`docs/agents/tasks-plan-b.md`). Путь `legacy`
пишет три последних числа только текстом заметок, поэтому скрипт читает шаблоны фраз —
и отдельный тест сторожит, что эти фразы всё ещё стоят в коде, который их пишет.
Иначе переформулированная заметка молча обнулила бы строку приёмки.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def plan_b() -> ModuleType:
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("plan_b_metrics")
    finally:
        sys.path.remove(str(scripts))


def choice(slide_id: str, intent: str, recipe: str, why: str) -> dict[str, Any]:
    return {"slide_id": slide_id, "intent": intent, "recipe_id": recipe, "why": why}


BY_SEATS = "заказанного вида нет — из 11 вмещающих взят ближайший по местам"
BY_MEANING = "заказан вид «cards» — взят рецепт этого вида"
BY_PLACE = "место в колоде задаёт вид «cover» — взят рецепт этого вида"


def report(choices: list[dict[str, Any]], notes: list[str] | None = None) -> dict[str, Any]:
    return {"run_id": "r1", "slide_choices": choices, "notes": notes or []}


def test_structural_slides_are_not_counted_as_by_meaning(plan_b: ModuleType) -> None:
    """Норма: обложка и финал в счёт «по смыслу» не входят ни числителем, ни знаменателем."""
    deck = plan_b.deck_metrics(
        report([
            choice("s01", "title", "ex001", BY_PLACE),
            choice("s02", "summary", "ex018", BY_MEANING),
            choice("s03", "evidence", "ex009", BY_SEATS),
            choice("s04", "closing", "ex006", BY_PLACE),
        ])
    )

    assert (deck.by_meaning, deck.content_slides) == (1, 2)


def test_a_repeated_example_is_counted_and_neighbours_named(plan_b: ModuleType) -> None:
    """Нарушитель: один пример на трёх слайдах, два из них подряд."""
    deck = plan_b.deck_metrics(
        report([
            choice("s01", "summary", "ex018", BY_SEATS),
            choice("s02", "problem", "ex018", BY_SEATS),
            choice("s03", "evidence", "ex009", BY_SEATS),
            choice("s04", "solution", "ex018", BY_SEATS),
        ])
    )

    assert (deck.top_example, deck.top_example_uses, deck.adjacent_repeats) == ("ex018", 3, 1)


def test_the_legacy_notes_are_sorted_into_rows(plan_b: ModuleType) -> None:
    """Нарушитель: заметки пути `legacy` ложатся в строки 4–6, остальные не считаются."""
    notes = [
        "слайд s02: блок b04 снят — свободной зоны в рецепте ex018 не осталось "
        "(мест под тело 2, блоков тела 3)",
        "слайд s03: блок b05 («chart») снят — рецепт ex018 ставит в зоны только текст",
        "слайд s02: блок b03 — повторов в рецепте ex018 1, пунктов 3; последние 2 сняты",
        "s05/b2: пункт «третий» выброшен — список не помещается в место макета",
        "слайд s04: блок b1 («smartart») поставлен в зону рецепта ex018 простым текстом "
        "— зона не несёт рисунка схемы",
        "слайд s06: блок b2 («callout») поставлен в зону рецепта ex018 простым текстом "
        "— зона не несёт плашки callout",
        "слайд s07: блок b1 обрезан до вместимости зоны z02 — было 120 знаков, осталось 90",
        "s01/b2: текст сокращён, чтобы влезть",
        "s08/b03: текст «Автоматически сверстать» снят — не помещается в место макета "
        "даже в два слова",
        "план: слайдов 10 вместо запрошенных 12 — на 24 фактах больше вышло бы полупустыми",
    ]
    deck = plan_b.deck_metrics(report([], notes))

    assert deck.dropped_blocks == 2
    assert deck.dropped_items == 3
    assert deck.flattened == {"callout": 1, "smartart": 1}
    assert deck.cut_by_code == 3


def test_a_clean_deck_has_zeros(plan_b: ModuleType) -> None:
    """Норма: без заметок о потерях строки 4–6 — нули, путь по умолчанию `legacy`."""
    deck = plan_b.deck_metrics(report([choice("s02", "summary", "ex018", BY_MEANING)]))

    assert (deck.dropped_blocks, deck.flattened_total, deck.cut_by_code) == (0, 0, 0)
    assert deck.composition_path == "legacy"


@pytest.mark.parametrize(
    ("source", "phrase"),
    [
        ("src/deckforge/composition/recipe_picker.py", "заказанного вида нет"),
        ("src/deckforge/composition/recipe_binding.py", "не осталось (мест под тело"),
        ("src/deckforge/composition/recipe_binding.py", "ставит в зоны только текст"),
        ("src/deckforge/composition/recipe_binding.py", "; последние {total - placed} сняты"),
        ("src/deckforge/composition/recipe_binding.py", "простым текстом — зона не несёт"),
        ("src/deckforge/composition/recipe_binding.py", "обрезан до вместимости зоны"),
        ("src/deckforge/pipeline/nodes/fit.py", "текст сокращён, чтобы влезть"),
        ("src/deckforge/pipeline/nodes/fit.py", "выброшен — список не помещается в место макета"),
        ("src/deckforge/pipeline/nodes/fit.py", "не помещается в место макета даже в два слова"),
    ],
)
def test_the_note_phrases_still_live_in_the_code(source: str, phrase: str) -> None:
    """Сторож: фраза, по которой скрипт считает строку, всё ещё пишется своим кодом.

    Переформулировали заметку — этот тест красный, и шаблон в скрипте правится вместе
    с ней. Без него строка приёмки молча показала бы ноль.
    """
    code = (ROOT / source).read_text(encoding="utf-8")
    flat = " ".join(line.strip().strip('f"') for line in code.splitlines())

    assert phrase in code or phrase in flat


def test_a_run_dir_is_read_as_the_stand_lays_it(
    plan_b: ModuleType, tmp_path: Path
) -> None:
    """Норма: стенд кладёт отчёт в `out/run.json` — скрипт находит его там."""
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "run.json").write_text('{"run_id": "abc"}', encoding="utf-8")

    assert plan_b.load_report(tmp_path)["run_id"] == "abc"
