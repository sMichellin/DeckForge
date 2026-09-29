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
from functools import partial
from typing import Any

from langgraph.runtime import Runtime

from deckforge.composition.assign import RecipeAssignment
from deckforge.composition.composer import SlideComposer
from deckforge.composition.layout_picker import LayoutPickError, pick_layout
from deckforge.composition.passport import Fits, fit_measure
from deckforge.designsystem import DesignSystem
from deckforge.designsystem.models import PlaceKind, Recipe, TypeLevel
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.domain.slide import SlideIR
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.layout.fonts import FontLibrary
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


def _bands_of_assigned_places(
    assignments: dict[str, RecipeAssignment],
    manifest: TemplateManifest,
    design_system: DesignSystem | None,
    fonts: FontLibrary | None,
) -> dict[str, Band]:
    """Полоса заголовка на пути `by_example` — место заголовка назначенного примера.

    Заголовок там встаёт не в полосу макета, а в место примера со своим пределом
    (change `the-text-is-written-for-the-places`, запрос 3 потока A). Мерить его полосой
    макета значило бы переписать заголовок под одну рамку, а потом просить его в другую.
    Мерило — то же вписывание, которым мерился паспорт (`passport.fit_measure`), предел —
    ёмкость места. Место заголовка под число (меньше двух слов) полосой не считается,
    как и полоса макета короче двух слов (`layout_headline_band`): переписывать под неё
    нечего, кегль спустит вёрстка.
    """
    if design_system is None or not assignments:
        return {}
    recipes = {r.recipe_id: r for r in design_system.recipes if r.passport is not None}
    fits = fit_measure(manifest, design_system, fonts)
    bands: dict[str, Band] = {}
    for slide_id, assignment in assignments.items():
        recipe = recipes.get(assignment.recipe_id or "")
        if recipe is None or recipe.passport is None:
            continue
        place = next(
            (p for p in recipe.passport.places
             if p.role is TypeLevel.SLIDE_TITLE and p.kind is PlaceKind.TEXT and p.zone_id),
            None,
        )
        if place is None or place.zone_id is None:
            continue
        bands[slide_id] = Band(
            fits=partial(_lands_in, fits, recipe, place.zone_id), limit=place.capacity_chars
        )
    return bands


def _lands_in(fits: Fits, recipe: Recipe, zone_id: str, text: str) -> bool:
    """Встаёт ли заголовок в место заголовка примера кеглем автора (мерило паспорта)."""
    return fits(recipe, {zone_id: text}).get(zone_id, False)


async def compose_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`DeckPlan` + манифест → `SlideIR` по слайду (changes 11, 20)."""
    deps = runtime.context
    client, degraded = deps.llm_for("compose")
    # Шрифты — те же, которыми мерился паспорт: на пути `by_example` текст под места
    # проверяется ими, а без них замер шёл бы оценкой по метрикам (запрос 1 потока A).
    composer = SlideComposer(client, profile=deps.prompt_profile, fonts=deps.fonts)
    # Заголовки под выбранный макет переписывает та же дешёвая модель, что и в узле
    # `plan`: скилл `headline_writer` объявлен на неё.
    rewriter = HeadlineRewriter(deps.llm_fast or client, profile=deps.prompt_profile)
    slots = deps.slots()
    plan = state["plan"]
    # Назначения узла `assign` (ADR-009, решение Р2). На пути `legacy` их нет, и композитор
    # идёт прежним путём байт в байт; есть — слайд пишется под места назначенного примера.
    assignments = {a.slide_id: a for a in state.get("assignments") or []}

    # Какой рецепт стоял на прошлом слайде: два одинаковых подряд читаются как один
    # перелистнутый назад (таск 05b). Порядок слайдов в плане и есть порядок колоды.
    order = {slide.slide_id: index for index, slide in enumerate(plan.slides)}
    picked: dict[int, str | None] = {}

    async def one(slide: SlidePlan) -> SlideIR:
        async with slots:
            # Дизайн-система — та же, что увидят `fit` и `render` (DG2, DG3): по ней
            # композиция называет модели роли цветов и разводит свободные блоки.
            composed = await composer.compose(
                slide, state["content"], state["manifest"], state["variant"], state["seed"],
                design_system=state.get("design_system"),
                previous_recipe=picked.get(order[slide.slide_id] - 1),
                assignment=assignments.get(slide.slide_id),
            )
            picked[order[slide.slide_id]] = composed.recipe_id
            return composed

    async with timed(deps, "compose") as timings:
        # A11. Предел планировщику назван по медиане полос шаблона, а макет слайду
        # выбирается только здесь: у VK Tech медиана 63 знака, выбранные макеты держат
        # 24–32, и композиция подрезала 7 заголовков из 9. Не встающие в полосу своего
        # макета уходят модели одной пачкой, до композиции, — а не режутся по словам.
        plan = await rewriter.rewrite_for_layouts(
            plan,
            state["content"],
            bands={
                **_bands_of_picked_layouts(plan, state["manifest"], state["variant"]),
                **_bands_of_assigned_places(
                    assignments, state["manifest"], state.get("design_system"), deps.fonts
                ),
            },
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

    # Композитор без объяснений (подделка в тестах) — выбор просто не показывается.
    choices: dict[str, Any] = getattr(composer, "choices", {})
    return {
        # План с заголовками под выбранные макеты: по нему дальше идут порядок колоды
        # и отчёт, и заголовок в плане не должен расходиться с заголовком на слайде.
        "plan": plan,
        "slides": slides,
        # Почему каждый слайд собран так — в порядке плана (Т7).
        "slide_choices": [
            choices[slide.slide_id] for slide in plan.slides if slide.slide_id in choices
        ],
        "stage_timings_s": timings,
        "errors": errors,
        # Что композиция поставила свободным блоком, отбросила или урезала: без этого
        # отчёт о потерянном содержании оставался внутри композитора (#59).
        "notes": [f"заголовок под макет: {note}" for note in rewriter.notes]
        + list(composer.notes),
        "degradations": [degraded] if degraded else [],
    }
