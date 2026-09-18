#!/usr/bin/env python3
"""Стабильность вердиктов VLM-судьи на N прогонах. Критерий выхода change (18).

ТЗ требует, чтобы вердикты совпадали на трёх прогонах в ≥ 80 % случаев. Проверить это
может только живая модель, поэтому замер вынесен в скрипт, а не в тест.

    DECKFORGE_MODELS_CONFIG=models.local.yaml \
    DECKFORGE_VLM_BASE_URL=http://<хост>:<порт>/v1 DECKFORGE_VLM_API_KEY=none \
    python scripts/bench_judge_stability.py <каталог замера> --runs 3

Каталог готовит `--prepare`: колода из макетов шаблона, запись .pptx и превью
(нужен LibreOffice, то есть образ воркера).

Три решения, без которых замер меряет не то.

**Кэш ответов выключается.** С ним второй и третий прогоны читают с диска, и стабильность
получается стопроцентной по построению.

**Голосование — по одному голосу.** Мажоритарное голосование трёх сидов существует ровно
затем, чтобы гасить разброс; замерять стабильность поверх него значит замерять
эффективность лекарства, а не болезнь. Цифра с `votes=1` — нижняя оценка: в бою
с `vlm_votes: 3` стабильность может быть только выше.

**Ячейка без вердикта не считается совпадением.** Если модель не ответила во всех трёх
прогонах, наивный счётчик засчитает это как «совпало» и завысит результат. Такие ячейки
выносятся в отдельную графу: «не ответила» — это не «ответила одинаково».
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.audit.geometry import slide_text
from deckforge.audit.semantic.judge import QUESTIONS, ask
from deckforge.domain.slide import DeckIR

#: Вопрос про пару слайдов: первому слайду не с чем соседствовать.
PAIRWISE = "content.neighbours_connected"

NO_ANSWER = "нет ответа"
OK = "ok"
FINDING = "находка"


@dataclass(slots=True)
class Cell:
    """Одна пара «слайд × вопрос» и её вердикты по прогонам."""

    slide_id: str
    check_id: str
    verdicts: list[str]

    @property
    def answered_everywhere(self) -> bool:
        return all(v != NO_ANSWER for v in self.verdicts)

    @property
    def agrees(self) -> bool:
        return len(set(self.verdicts)) == 1

    @property
    def accuses(self) -> bool:
        return any(v == FINDING for v in self.verdicts)


def measure(
    deck: DeckIR, previews: dict[str, bytes], judge_factory: object, runs: int
) -> list[Cell]:
    """N независимых прогонов судьи по каждому слайду и каждому вопросу."""
    slides = list(deck.slides)
    collected: dict[tuple[str, str], list[str]] = {}

    for _ in range(runs):
        judge = judge_factory()  # type: ignore[operator]
        for index, slide in enumerate(slides):
            image = previews.get(slide.slide_id)
            if image is None:
                continue
            for check_id, question in QUESTIONS.items():
                context = ""
                if check_id == PAIRWISE:
                    if index == 0:
                        continue
                    context = f"Предыдущий слайд: {slide_text(slides[index - 1])[:600]}"
                verdict = ask(
                    judge,
                    check_id=check_id,
                    question=question,
                    image_png=image,
                    language=deck.language,
                    context=context,
                    votes=1,
                )
                collected.setdefault((slide.slide_id, check_id), []).append(
                    NO_ANSWER if verdict is None else (OK if verdict.ok else FINDING)
                )

    return [
        Cell(slide_id=slide_id, check_id=check_id, verdicts=verdicts)
        for (slide_id, check_id), verdicts in collected.items()
    ]


def report(cells: list[Cell], threshold: float) -> bool:
    """Печатает результат и отвечает, выполнен ли критерий ТЗ."""
    answered = [c for c in cells if c.answered_everywhere]
    unanswered = [c for c in cells if not c.answered_everywhere]
    agreed = [c for c in answered if c.agrees]
    accusing = [c for c in cells if c.accuses]

    share = len(agreed) / len(answered) if answered else 0.0
    print(f"\nячеек (слайд × вопрос): {len(cells)}")
    print(f"  с вердиктом во всех прогонах: {len(answered)}")
    print(f"  совпали: {len(agreed)} — {share * 100:.0f} % при пороге {threshold * 100:.0f} %")
    print(f"  модель не ответила: {len(unanswered)}")

    # Без этой строки цифра ничего не значит: согласие на «претензий нет» даётся даром.
    print(f"\nячеек с обвинением хотя бы в одном прогоне: {len(accusing)}")
    stable_accusations = sum(1 for c in accusing if c.agrees and c.answered_everywhere)
    print(f"  из них воспроизвелись во всех прогонах: {stable_accusations}")

    by_question = Counter(c.check_id for c in accusing)
    if by_question:
        print("\nобвинения по вопросам:")
        for check_id, count in by_question.most_common():
            print(f"  {count:>4}  {check_id}")

    unstable = [c for c in answered if not c.agrees]
    for cell in [*unstable, *unanswered]:
        print(f"  ! {cell.slide_id} / {cell.check_id}: {cell.verdicts}")

    return share >= threshold


def load(work: Path) -> tuple[DeckIR, dict[str, bytes]]:
    deck = DeckIR.model_validate_json((work / "deck.json").read_text(encoding="utf-8"))
    paths = json.loads((work / "previews.json").read_text(encoding="utf-8"))
    return deck, {k: Path(v).read_bytes() for k, v in paths.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path, help="Каталог с deck.json и previews.json")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=0.8, help="Порог ТЗ")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    from deckforge.inference.factory import vlm_judge

    deck, previews = load(args.work)
    print(f"слайдов {len(deck.slides)}, вопросов {len(QUESTIONS)}, прогонов {args.runs}")

    started = time.perf_counter()
    # Кэш выключен намеренно: с ним замер показал бы 100 % на любой модели.
    cells = measure(deck, previews, lambda: vlm_judge("vlm_judge", use_cache=False), args.runs)
    elapsed = time.perf_counter() - started
    calls = sum(len(c.verdicts) for c in cells)
    print(f"вызовов {calls}, {elapsed:.0f} с ({elapsed / calls:.1f} с на вызов)")

    ok = report(cells, args.threshold)

    if args.out:
        args.out.write_text(
            json.dumps(
                [
                    {"slide_id": c.slide_id, "check_id": c.check_id, "verdicts": c.verdicts}
                    for c in cells
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nнаписано {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
