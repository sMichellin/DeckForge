"""Детерминированные правила нарратива: одна мысль на слайд, связность соседей.

Change (10) `deck-planning`. Правила проверяются **после** ответа модели: схема
гарантирует форму, но не смысл. Каркасы по назначениям — решение владельца потока A,
обоснование в `openspec/changes/deck-planning/proposal.md`.
"""

from __future__ import annotations

from typing import Final

from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import DeckPlan, NarrativeCheck

#: Заголовок длиннее не прочитают за те секунды, что смотрят на слайд.
MAX_HEADLINE_WORDS: Final = 10

#: Ни одна роль не занимает больше половины колоды: иначе двенадцать однотипных слайдов.
MAX_ROLE_SHARE: Final = 0.5

#: Обязательный каркас по назначению из ТЗ. Порядок значим, промежуточные слайды
#: добираются по материалу.
MANDATORY_FRAMES: Final[dict[str, tuple[SlideIntent, ...]]] = {
    "feature": (
        SlideIntent.TITLE,
        SlideIntent.PROBLEM,
        SlideIntent.SOLUTION,
        SlideIntent.EVIDENCE,
        SlideIntent.CLOSING,
    ),
    "product": (
        SlideIntent.TITLE,
        SlideIntent.PROBLEM,
        SlideIntent.SOLUTION,
        SlideIntent.METRICS,
        SlideIntent.ROADMAP,
        SlideIntent.CLOSING,
    ),
    # Сначала система координат, потом проблема: комитет должен понять положение дел,
    # прежде чем слушать про отставание.
    "project": (
        SlideIntent.TITLE,
        SlideIntent.METRICS,
        SlideIntent.PROBLEM,
        SlideIntent.SOLUTION,
        SlideIntent.ROADMAP,
        SlideIntent.CLOSING,
    ),
    "initiative": (
        SlideIntent.TITLE,
        SlideIntent.PROBLEM,
        SlideIntent.SOLUTION,
        SlideIntent.COMPARISON,
        SlideIntent.CLOSING,
    ),
    # Сводка второй: отчёт о проблеме читают встревоженные люди, держать их
    # в неведении до середины колоды нельзя.
    "report": (
        SlideIntent.TITLE,
        SlideIntent.SUMMARY,
        SlideIntent.PROBLEM,
        SlideIntent.EVIDENCE,
        SlideIntent.SOLUTION,
        SlideIntent.CLOSING,
    ),
}

#: Роли, любая из которых считается «главным выводом» колоды.
_CONCLUSION_INTENTS: Final = frozenset({SlideIntent.SUMMARY, SlideIntent.SOLUTION})

#: Насколько рано должен прозвучать вывод в пирамидальном порядке.
_PYRAMID_POSITION: Final = 3


def _frame_is_subsequence(frame: tuple[SlideIntent, ...], intents: list[SlideIntent]) -> bool:
    """Каркас обязателен по составу и порядку, но не обязан идти подряд."""
    position = 0
    for intent in intents:
        if position < len(frame) and intent == frame[position]:
            position += 1
    return position == len(frame)


def check_narrative(
    plan: DeckPlan, purpose: str | None = None, grouping: str | None = None
) -> NarrativeCheck:
    """Проверяет план по правилам, которые не выражаются схемой."""
    notes: list[str] = []
    intents = [slide.intent for slide in plan.slides]

    long_headlines = [
        slide.slide_id
        for slide in plan.slides
        if len(slide.headline.split()) > MAX_HEADLINE_WORDS
    ]
    if long_headlines:
        notes.append(
            f"заголовок длиннее {MAX_HEADLINE_WORDS} слов: {', '.join(long_headlines)}"
        )

    if plan.slides and intents[-1] != SlideIntent.CLOSING:
        notes.append("последний слайд не несёт целевого действия (роль не closing)")

    frame = MANDATORY_FRAMES.get(purpose or "")
    if frame and not _frame_is_subsequence(frame, intents):
        expected = " → ".join(item.value for item in frame)
        notes.append(f"каркас назначения {purpose!r} нарушен, ожидался порядок: {expected}")

    if plan.slides:
        for intent in set(intents):
            share = intents.count(intent) / len(intents)
            if share > MAX_ROLE_SHARE:
                notes.append(
                    f"роль {intent.value} занимает {share:.0%} колоды при пределе "
                    f"{MAX_ROLE_SHARE:.0%}"
                )

    conclusion_at = next(
        (i for i, intent in enumerate(intents, start=1) if intent in _CONCLUSION_INTENTS),
        None,
    )
    if conclusion_at is None:
        notes.append("в колоде нет слайда с главным выводом (роль summary или solution)")
    elif grouping == "pyramid" and conclusion_at > _PYRAMID_POSITION:
        notes.append(
            f"пирамидальный порядок: вывод на слайде {conclusion_at}, "
            f"допустимо не позже {_PYRAMID_POSITION}"
        )

    return NarrativeCheck(
        one_idea_per_slide=not long_headlines,
        has_arc=not any(
            note.startswith(("каркас", "последний слайд", "в колоде нет")) for note in notes
        ),
        notes=notes,
    )
