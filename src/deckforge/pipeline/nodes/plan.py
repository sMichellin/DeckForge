"""Узел `plan`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

from collections.abc import Callable

from langgraph.runtime import Runtime

from deckforge.domain.enums import TextRole
from deckforge.domain.slide import TextBlock
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.layout.fitting import fit_block
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState
from deckforge.planning.headlines import HeadlineRewriter
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

    Меряется `fit_block` — тем же кодом, что и вёрстка, со всеми его правилами, включая
    уступку кегля до ступени тела (A9). Мера ограничена длиной образца: полоса, которая
    держит его целиком, заголовок больше не ограничивает, и дальше решает правило десяти
    слов — см. `headline_limit`.
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


def _median_title_slot(manifest: TemplateManifest) -> tuple[int, LayoutSpec, int] | None:
    """Полоса заголовка с медианной вместимостью и её мера в знаках.

    Декоративные обложки в выборку не берутся: у VK Education такая полоса держит семь
    знаков и продиктовала бы длину всей колоде. Медиана, а не минимум; макетам теснее
    медианы заголовок подрежет композиция.
    """
    with_body = [item for item in manifest.layouts if item.capacity.max_chars_body > 0]
    slots = [
        (item, ph.idx)
        for item in (with_body or manifest.layouts)
        for ph in item.placeholders
        if ph.role is TextRole.TITLE
    ]
    if not slots:
        return None
    measured = sorted(
        ((_chars_that_fit(item, idx, manifest), item, idx) for item, idx in slots),
        key=lambda row: row[0],
    )
    return measured[len(measured) // 2]


def headline_limit(manifest: TemplateManifest) -> int:
    """Предел заголовка по измерению — типичный макет, который несёт содержание.

    Оценка по средней ширине знака врёт вдвое (46 знаков вместо 27 на VK WorkSpace),
    и планировщик просил заведомо длинные заголовки: все двенадцать обрезались многоточием
    (прогоны d573740bddd3, 05884387b999, eab2860439e7).

    Сверху предел ограничен правилом десяти слов (A9). После уступки кегля полосы шаблонов
    кейса держат образец целиком, и мера упирается в его длину — то есть перестаёт быть
    мерой шаблона. Заголовок длиной в сто знаков — уже не вывод, а абзац, и просить его
    у модели незачем, какой бы просторной ни была полоса.
    """
    slot = _median_title_slot(manifest)
    if slot is None:
        return DEFAULT_HEADLINE_CHARS
    measured = max(MIN_HEADLINE_CHARS, slot[0] or DEFAULT_HEADLINE_CHARS)
    return min(DEFAULT_HEADLINE_CHARS, measured)


def headline_fits(manifest: TemplateManifest) -> Callable[[str], bool]:
    """Мерило для слоя `planning`: встанет ли этот заголовок в полосу макета.

    Слой планирования не имеет права импортировать `layout` (правило 1 AGENTS.md),
    поэтому измерение уезжает туда функцией. Меряется тем же `fit_block`, что и вёрстка,
    по представительной полосе шаблона.

    Заголовок не длиннее объявленного предела считается уместившимся без измерения:
    на тесных шаблонах предел поднят до нижнего порога (25 знаков), и мерить строго
    значило бы гонять модель за заголовками в семь знаков, которых мы и не просили.
    """
    slot = _median_title_slot(manifest)
    limit = headline_limit(manifest)

    def fits(text: str) -> bool:
        if len(text) <= limit or slot is None:
            return True
        _, layout, idx = slot
        probe = TextBlock(
            block_id="probe", placeholder_idx=idx, role=TextRole.TITLE, text=text
        )
        return not fit_block(probe, layout, manifest).overflow

    return fits


async def plan_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`ContentPackage` + виды макетов → `DeckPlan` (change 10). Один вызов LLM."""
    deps = runtime.context
    client, degraded = deps.llm_for("plan")
    planner = DeckPlanner(client, profile=deps.prompt_profile)

    limit = headline_limit(state["manifest"])
    fits_band = headline_fits(state["manifest"])
    # Заголовки переписывает дешёвая модель: скилл `headline_writer` объявлен на неё,
    # и вызовов столько же, сколько не уместившихся заголовков.
    rewriter = HeadlineRewriter(deps.llm_fast or client, profile=deps.prompt_profile)

    async with timed(deps, "plan") as timings:
        plan = await planner.plan(
            state["content"],
            state["manifest"],
            state["variant"],
            state["seed"],
            headline_limit=limit,
        )
        # Предел модели назван, но она его не держит (прогон ea732e59510c: 9 заголовков
        # из 10 длиннее места). Не уместившийся заголовок переписывается моделью, а не
        # режется кодом: обрубок с многоточием теряет вывод, ради которого заголовок и был.
        plan = await rewriter.rewrite_overlong(
            plan,
            state["content"],
            fits=fits_band,
            limit=limit,
            seed=state["seed"],
            slots=deps.slots(),
        )

    # Нарратив проверен планировщиком, но чинить его молча нельзя (change 10):
    # замечания едут в отчёт прогона, а не растворяются внутри слоя.
    notes = [f"план: {note}" for note in plan.narrative_check.notes]
    notes += [f"план: {note}" for note in rewriter.notes]

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
