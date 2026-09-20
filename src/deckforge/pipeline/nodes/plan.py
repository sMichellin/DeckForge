"""Узел `plan`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

from langgraph.runtime import Runtime

from deckforge.domain.enums import TextRole
from deckforge.domain.slide import TextBlock
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.layout.fitting import fit_block
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState
from deckforge.planning.planner import (
    DEFAULT_HEADLINE_CHARS,
    MIN_HEADLINE_CHARS,
    DeckPlanner,
    slides_for,
)

#: Строка, на которой меряется полоса заголовка. Обычная деловая фраза по-русски:
#: у кириллицы своя ширина знака, и «средний знак» её не описывает.
_HEADLINE_SAMPLE = (
    "Выручка выросла на треть за счёт корпоративных клиентов "
    "и новых рынков сбыта за прошедший год работы"
)


def _chars_that_fit(layout: LayoutSpec, idx: int, manifest: TemplateManifest) -> int:
    """Самая длинная фраза, которая влезает в эту полосу заголовка.

    Меряется `fit_block` — тем же кодом, что и вёрстка, со всеми его правилами: заголовок
    кеглем не уменьшается, кроме случая, когда полоса не держит и одной строки.
    """
    kept: list[str] = []
    for word in _HEADLINE_SAMPLE.split():
        probe = TextBlock(
            block_id="probe",
            placeholder_idx=idx,
            role=TextRole.TITLE,
            text=" ".join([*kept, word]),
        )
        if fit_block(probe, layout, manifest).overflow:
            break
        kept.append(word)
    return len(" ".join(kept))


def headline_limit(manifest: TemplateManifest) -> int:
    """Предел заголовка по измерению — типичный макет, который несёт содержание.

    Оценка по средней ширине знака врёт вдвое (46 знаков вместо 27 на VK WorkSpace),
    и планировщик просил заведомо длинные заголовки: все двенадцать обрезались многоточием
    (прогоны d573740bddd3, 05884387b999, eab2860439e7).

    Декоративные обложки в выборку не берутся: у VK Education такая полоса держит семь
    знаков и продиктовала бы длину всей колоде. Берётся медиана, а не минимум; макетам
    теснее медианы заголовок подрежет композиция.
    """
    with_body = [item for item in manifest.layouts if item.capacity.max_chars_body > 0]
    slots = [
        (item, ph.idx)
        for item in (with_body or manifest.layouts)
        for ph in item.placeholders
        if ph.role is TextRole.TITLE
    ]
    if not slots:
        return DEFAULT_HEADLINE_CHARS
    limits = sorted(_chars_that_fit(item, idx, manifest) for item, idx in slots)
    return max(MIN_HEADLINE_CHARS, limits[len(limits) // 2] or DEFAULT_HEADLINE_CHARS)


async def plan_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`ContentPackage` + виды макетов → `DeckPlan` (change 10). Один вызов LLM."""
    deps = runtime.context
    client, degraded = deps.llm_for("plan")
    planner = DeckPlanner(client, profile=deps.prompt_profile)

    async with timed(deps, "plan") as timings:
        plan = await planner.plan(
            state["content"],
            state["manifest"],
            state["variant"],
            state["seed"],
            headline_limit=headline_limit(state["manifest"]),
        )

    # Нарратив проверен планировщиком, но чинить его молча нельзя (change 10):
    # замечания едут в отчёт прогона, а не растворяются внутри слоя.
    notes = [f"план: {note}" for note in plan.narrative_check.notes]

    # Материала может не хватить на запрошенное число слайдов. Урезать молча нельзя:
    # автор просил двенадцать и должен узнать, почему их восемь.
    brief = state["content"].brief
    fits = slides_for(state["content"], brief.purpose, brief.target_slides)
    if fits < brief.target_slides:
        notes.append(
            f"план: слайдов {len(plan.slides)} вместо запрошенных {brief.target_slides} — "
            f"на {len(state['content'].facts)} фактах больше вышло бы полупустыми"
        )
    return {
        "plan": plan,
        "stage_timings_s": timings,
        "notes": notes,
        "degradations": [degraded] if degraded else [],
    }
