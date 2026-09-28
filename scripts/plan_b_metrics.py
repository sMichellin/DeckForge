#!/usr/bin/env python3
"""Мерило плана Б: таблица приёмки по готовым прогонам (`docs/agents/tasks-plan-b.md`).

Зачем. С 24.09 качество колоды мерилось числом ошибок аудита, и 28.09 51 ошибка из 55
оказалась ложной: замер обвинял нашу же работу. План Б принимается по другим числам —
выбран ли пример по смыслу, сколько раз он повторён, сколько блоков снято, сплющено
и обрезано кодом. Скрипт считает их по `run.json` прогона и ничего не запускает.

Откуда берётся каждое число:

* выбор примера и повторы — `slide_choices` (рецепт и причина выбора словами, Т7);
* снятые, сплющенные и обрезанные блоки — `notes` прогона. Путь `legacy` пишет их только
  текстом, поэтому шаблоны фраз ниже сняты с кода, который их пишет, и сторожатся
  тестом: переформулировали заметку — тест покраснеет, а не число молча обнулится.

Строка 7 — блоки ниже порога читаемости — считается по файлу колоды тем же замером,
что `scripts/check_deck_readable.py` (change `the-seventh-row-is-measured`): только если
рядом с отчётом лежит `out/deck.pptx`. У фикстур файла нет, у прогонов стенда есть.

Строка 3 — пустые карточки — берётся из находок проверки `integrity.empty_group`
(поток C, #255) в `run.json`: сколько слайдов с ней. Только если проверку знал код прогона
(`checks_known`) и она не пропущена; иначе прочерк, а не ноль: «не мерили» и «ноль» —
разные ответы (change `the-third-row-is-measured`).

    python scripts/plan_b_metrics.py artifacts/runs/2026-09-28-main-19e3b7e/*/
    python scripts/plan_b_metrics.py --json <каталог прогона> …
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Интенты плана, которым пример задаёт место в колоде, а не смысл: обложка, раздел, финал.
#: План Б считает «пример по смыслу» только на содержательных слайдах.
STRUCTURAL_INTENTS = frozenset({"title", "section", "closing"})

#: Начало причины выбора, когда заказанного вида у шаблона нет и пример взят по местам
#: (`composition/recipe_picker.py`, путь `fitting`). Это ровно «не по смыслу».
_BY_SEATS = "заказанного вида нет"

#: Шаблоны заметок пути `legacy`. Источник каждого — в комментарии; менять вместе с ним.
_DROPPED_BLOCK = re.compile(
    # recipe_binding: «блок X снят — свободной зоны…», «блок X («тип») снят — рецепт…»
    r"^слайд (?P<slide>s\d+): блок (?P<block>\S+)(?: \(«[^»]+»\))? снят — "
)
_DROPPED_ITEMS = re.compile(
    # recipe_binding: «…; последние N сняты»
    r"^слайд (?P<slide>s\d+): блок (?P<block>\S+) — повторов в рецепте .*; "
    r"последние (?P<count>\d+) сняты$"
)
_DROPPED_ITEM = re.compile(
    # pipeline/nodes/fit: «s01/b2: пункт «…» выброшен — список не помещается…»
    r"^(?P<slide>s\d+)/(?P<block>\S+): пункт «.*» выброшен — "
)
_FLATTENED = re.compile(
    # recipe_binding: «блок X («smartart») поставлен в зону рецепта … простым текстом»
    r"^слайд (?P<slide>s\d+): блок (?P<block>\S+) \(«(?P<type>[^»]+)»\) поставлен "
    r"в зону рецепта \S+ простым текстом"
)
_CUT_BY_CODE = (
    # recipe_binding: «блок X обрезан до вместимости зоны…»
    re.compile(r"^слайд (?P<slide>s\d+): блок (?P<block>\S+) обрезан до вместимости зоны "),
    # pipeline/nodes/fit: «s01/b2: текст сокращён, чтобы влезть»
    re.compile(r"^(?P<slide>s\d+)/(?P<block>\S+): текст сокращён, чтобы влезть$"),
    # pipeline/nodes/fit: «s08/b03: текст «…» снят — не помещается… даже в два слова»
    re.compile(
        r"^(?P<slide>s\d+)/(?P<block>\S+): (?:текст|блок \S+) «.*» снят — "
        r"не помещается в место макета даже в два слова$"
    ),
)


@dataclass
class DeckMetrics:
    """Строки таблицы приёмки плана Б для одной колоды."""

    run_id: str
    composition_path: str
    content_slides: int = 0
    #: Строка 1: пример выбран по смыслу, а не «ближайший по местам» — с примером или без.
    by_meaning: int = 0
    #: Строка 1, что лечит план Б: пример взят по местам, а не по смыслу. Цель — 0.
    by_seats: int = 0
    #: Строка 1: слайд получил пример по смыслу.
    with_example: int = 0
    #: Строка 1: примера нет, слайд собран дизайн-системой (ADR-009). Законный путь, но
    #: видимый отдельно: иначе строку «по смыслу» можно выполнить, не назначив ни одного
    #: примера (замечание потока A к #248).
    by_design: int = 0
    #: Строка 2: самый частый пример колоды и сколько раз он стоит.
    top_example: str | None = None
    top_example_uses: int = 0
    #: Строка 2: пары соседних слайдов на одном примере.
    adjacent_repeats: int = 0
    #: Строка 4: блоков снято из-за нехватки мест.
    dropped_blocks: int = 0
    #: Не строка приёмки, но того же рода: пунктов списка снято.
    dropped_items: int = 0
    #: Строка 5: блоков, сплющенных в текст, по видам.
    flattened: dict[str, int] = field(default_factory=dict)
    #: Строка 6: блоков, обрезанных или снятых кодом вписывания.
    cut_by_code: int = 0
    #: Строка 3: слайдов с пустой группой примера; `None` — проверка не шла.
    empty_cards: int | None = None
    #: Строка 7: блоков ниже порога читаемости по файлу колоды; `None` — файла нет.
    below_floor: int | None = None

    @property
    def flattened_total(self) -> int:
        return sum(self.flattened.values())


def deck_metrics(report: dict[str, Any]) -> DeckMetrics:
    """Метрики одной колоды по её `run.json`."""
    metrics = DeckMetrics(
        run_id=str(report.get("run_id") or "?"),
        composition_path=str(report.get("composition_path") or "legacy"),
    )
    choices = list(report.get("slide_choices") or [])
    content = [c for c in choices if c.get("intent") not in STRUCTURAL_INTENTS]
    metrics.content_slides = len(content)
    metrics.by_seats = sum(1 for c in content if str(c.get("why") or "").startswith(_BY_SEATS))
    metrics.by_meaning = len(content) - metrics.by_seats
    metrics.by_design = sum(
        1 for c in content
        if not c.get("recipe_id") and not str(c.get("why") or "").startswith(_BY_SEATS)
    )
    metrics.with_example = metrics.by_meaning - metrics.by_design

    examples = [c.get("recipe_id") for c in choices]
    uses = Counter(example for example in examples if example)
    if uses:
        metrics.top_example, metrics.top_example_uses = uses.most_common(1)[0]
    metrics.adjacent_repeats = sum(
        1 for left, right in pairwise(examples) if left and left == right
    )

    flattened: Counter[str] = Counter()
    for note in report.get("notes") or []:
        text = str(note)
        if _DROPPED_BLOCK.match(text):
            metrics.dropped_blocks += 1
        elif match := _DROPPED_ITEMS.match(text):
            metrics.dropped_items += int(match["count"])
        elif _DROPPED_ITEM.match(text):
            metrics.dropped_items += 1
        elif match := _FLATTENED.match(text):
            flattened[match["type"]] += 1
        elif any(pattern.match(text) for pattern in _CUT_BY_CODE):
            metrics.cut_by_code += 1
    metrics.flattened = dict(sorted(flattened.items()))
    metrics.empty_cards = _empty_cards(report)
    return metrics


#: Проверка потока C, по которой считается строка 3 (#255).
EMPTY_GROUP = "integrity.empty_group"


def _empty_cards(report: dict[str, Any]) -> int | None:
    """Строка 3: слайды с пустой группой примера — или `None`, если проверка не шла."""
    known = report.get("checks_known") or []
    if EMPTY_GROUP not in known or EMPTY_GROUP in (report.get("skipped_checks") or []):
        return None
    return len({
        finding.get("slide_id")
        for finding in report.get("findings_detail") or []
        if finding.get("check_id") == EMPTY_GROUP
    })


def below_floor(run_dir: Path) -> int | None:
    """Строка 7: сколько блоков колоды набрано ниже порога читаемости.

    Считает `check_deck_readable.check_deck` — тот же замер, что приёмка итерации 25.09,
    — а здесь только сводится: блок — пара «слайд, фигура», сколько бы прогонов текста
    в ней ни было. Шаблон рядом (`in/template.pptx`) — чтобы пустые рамки автора не шли
    в счёт. Файла колоды нет — `None`, а не ноль.
    """
    deck = run_dir / "out" / "deck.pptx"
    if not deck.is_file():
        return None
    import check_deck_readable as readable

    template = run_dir / "in" / "template.pptx"
    report = readable.check_deck(
        deck,
        size_floor_pt=readable.DEFAULT_SIZE_FLOOR_PT,
        library=readable._library(),
        filled=readable.filled_in_template(template if template.is_file() else None),
        outside=readable.outside_in_template(template if template.is_file() else None),
    )
    return len({
        (finding.slide, finding.shape)
        for finding in report.findings
        if finding.kind == readable.BELOW_FLOOR
    })


def load_report(run_dir: Path) -> dict[str, Any]:
    """`run.json` каталога прогона: как его кладёт стенд (`out/run.json`) или рядом."""
    for candidate in (run_dir / "out" / "run.json", run_dir / "run.json"):
        if candidate.is_file():
            data: dict[str, Any] = json.loads(candidate.read_text(encoding="utf-8"))
            return data
    raise FileNotFoundError(f"{run_dir}: нет ни out/run.json, ни run.json")


def table(decks: list[DeckMetrics]) -> str:
    """Таблица приёмки: строки плана Б, колонка на колоду."""
    head = "| # | Метрика | " + " | ".join(d.run_id for d in decks) + " |"
    rule = "|---|---|" + "---|" * len(decks)

    def row(number: str, name: str, cells: list[str]) -> str:
        return f"| {number} | {name} | " + " | ".join(cells) + " |"

    def flat(d: DeckMetrics) -> str:
        detail = ", ".join(f"{kind} {n}" for kind, n in d.flattened.items())
        return f"{d.flattened_total} ({detail})" if detail else "0"

    lines = [
        head,
        rule,
        row("", "Путь сборки", [d.composition_path for d in decks]),
        row("1", "Пример по местам, а не по смыслу",
            [f"{d.by_seats} из {d.content_slides}" for d in decks]),
        row("1", "…с примером по смыслу", [f"{d.with_example}" for d in decks]),
        row("1", "…путём дизайн-системы, без примера", [f"{d.by_design}" for d in decks]),
        row(
            "2",
            "Один пример на колоду, максимум",
            [f"{d.top_example_uses} ({d.top_example})" for d in decks],
        ),
        row("2", "Соседних слайдов на одном примере", [str(d.adjacent_repeats) for d in decks]),
        row("3", "Слайдов с пустой карточкой",
            ["—" if d.empty_cards is None else str(d.empty_cards) for d in decks]),
        row("4", "Блоков снято из-за нехватки мест", [str(d.dropped_blocks) for d in decks]),
        row("", "…и пунктов списка снято", [str(d.dropped_items) for d in decks]),
        row("5", "Блоков сплющено в текст", [flat(d) for d in decks]),
        row("6", "Обрезка или снятие текста кодом", [str(d.cut_by_code) for d in decks]),
        row("7", "Блоков ниже порога читаемости",
            ["—" if d.below_floor is None else str(d.below_floor) for d in decks]),
    ]
    by_seats = sum(d.by_seats for d in decks)
    with_example = sum(d.with_example for d in decks)
    content = sum(d.content_slides for d in decks)
    lines.append("")
    lines.append(
        f"Итого по местам: {by_seats} из {content}; с примером по смыслу: {with_example}. "
        "«—» — этим скриптом не мерится."
    )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("runs", nargs="+", type=Path, help="каталоги прогонов")
    parser.add_argument("--json", action="store_true", help="вывести JSON, а не таблицу")
    args = parser.parse_args(argv)

    decks = []
    for run in args.runs:
        deck = deck_metrics(load_report(run))
        deck.below_floor = below_floor(run)
        decks.append(deck)
    if args.json:
        print(json.dumps([asdict(d) for d in decks], ensure_ascii=False, indent=2))
    else:
        print(table(decks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
