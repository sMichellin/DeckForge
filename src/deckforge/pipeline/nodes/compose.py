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
from deckforge.composition.layout_picker import LayoutPickError, pick_layout
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.domain.slide import SlideIR
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.nodes.plan import layout_headline_band
from deckforge.pipeline.state import DeckState
from deckforge.planning.headlines import Band, HeadlineRewriter


def _bands_of_picked_layouts(
    plan: DeckPlan, manifest: TemplateManifest, variant: VariantProfile
) -> dict[str, Band]:
    """Полоса заголовка того макета, который композиция выберет каждому слайду.

    `pick_layout` детерминирован и от заголовка не зависит: здесь и в композиторе
    слайд получает один и тот же макет, а переписанный заголовок выбор не сдвигает.
    Слайд, которому макета не нашлось, пропускается — его сорвёт композиция и назовёт
    в отчёте, мерить тут нечего.
    """
    bands: dict[str, Band] = {}
    for slide in plan.slides:
        try:
            layout = pick_layout(slide, manifest, variant)
        except LayoutPickError:
            continue
        if (band := layout_headline_band(layout, manifest)) is not None:
            bands[slide.slide_id] = band
    return bands


async def compose_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`DeckPlan` + манифест → `SlideIR` по слайду (changes 11, 20)."""
    deps = runtime.context
    client, degraded = deps.llm_for("compose")
    composer = SlideComposer(client, profile=deps.prompt_profile)
    # Заголовки под выбранный макет переписывает та же дешёвая модель, что и в узле
    # `plan`: скилл `headline_writer` объявлен на неё.
    rewriter = HeadlineRewriter(deps.llm_fast or client, profile=deps.prompt_profile)
    slots = deps.slots()
    plan = state["plan"]

    async def one(slide: SlidePlan) -> SlideIR:
        async with slots:
            return await composer.compose(
                slide, state["content"], state["manifest"], state["variant"], state["seed"]
            )

    async with timed(deps, "compose") as timings:
        # A11. Предел планировщику назван по медиане полос шаблона, а макет слайду
        # выбирается только здесь: у VK Tech медиана 63 знака, выбранные макеты держат
        # 24–32, и композиция подрезала 7 заголовков из 9. Не встающие в полосу своего
        # макета уходят модели одной пачкой, до композиции, — а не режутся по словам.
        plan = await rewriter.rewrite_for_layouts(
            plan,
            state["content"],
            bands=_bands_of_picked_layouts(plan, state["manifest"], state["variant"]),
            # Заходы узла `plan` взяли `seed` и `seed + 1`: этот заход идёт следующим.
            seed=state["seed"] + 2,
        )
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
        # План с заголовками под выбранные макеты: по нему дальше идут порядок колоды
        # и отчёт, и заголовок в плане не должен расходиться с заголовком на слайде.
        "plan": plan,
        "slides": slides,
        "stage_timings_s": timings,
        "errors": errors,
        # Что композиция поставила свободным блоком, отбросила или урезала: без этого
        # отчёт о потерянном содержании оставался внутри композитора (#59).
        "notes": [f"заголовок под макет: {note}" for note in rewriter.notes]
        + list(composer.notes),
        "degradations": [degraded] if degraded else [],
    }
