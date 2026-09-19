"""Узел `compose`. Change (17) `pipeline-orchestration`.

Слайды собираются параллельно (§12: 100 с на композицию колоды), число одновременных
вызовов ограничено `parallel_slides`: без ограничителя двенадцать запросов уходят
в бэкенд разом и очередь на стороне сервера съедает выигрыш.

Веер `Send` не используется намеренно: он кладёт манифест и контент-пакет в чекпойнт
по разу на слайд. Ту же параллельность даёт `asyncio.gather` с семафором, а редьюсер
`_merge_slides` остаётся нужен — на витке фиксов пересобранный слайд замещает прежний.
"""

from __future__ import annotations

import asyncio

from langgraph.runtime import Runtime

from deckforge.composition.composer import SlideComposer
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import SlideIR
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


async def compose_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`DeckPlan` + манифест → `SlideIR` по слайду (changes 11, 20)."""
    deps = runtime.context
    client, degraded = deps.llm_for("compose")
    composer = SlideComposer(client, profile=deps.prompt_profile)
    slots = deps.slots()
    plan = state["plan"]

    async def one(slide: SlidePlan) -> SlideIR:
        async with slots:
            return await composer.compose(
                slide, state["content"], state["manifest"], state["variant"], state["seed"]
            )

    async with timed(deps, "compose") as timings:
        results = await asyncio.gather(
            *(one(slide) for slide in plan.slides), return_exceptions=True
        )

    slides: list[SlideIR] = []
    errors: list[str] = []
    for slide, result in zip(plan.slides, results, strict=True):
        if isinstance(result, BaseException):
            # Колода из одиннадцати слайдов лучше, чем отсутствие колоды: сорвавшийся
            # слайд называется в отчёте, а не роняет прогон.
            errors.append(f"слайд {slide.slide_id} не собран: {result}")
        else:
            slides.append(result)

    if not slides:
        raise RuntimeError(f"не собран ни один слайд из {len(plan.slides)}: {'; '.join(errors)}")

    return {
        "slides": slides,
        "stage_timings_s": timings,
        "errors": errors,
        # Что композиция поставила свободным блоком, отбросила или урезала: без этого
        # отчёт о потерянном содержании оставался внутри композитора (#59).
        "notes": list(composer.notes),
        "degradations": [degraded] if degraded else [],
    }
