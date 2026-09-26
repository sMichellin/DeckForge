"""Состав и порядок слайдов. Change (10) `deck-planning`.

Заголовок обязан быть **выводом**, а не темой: требование закладывается в промпт
`deck_planner`, а не чинится авто-фиксом после.

Планировщик не видит шаблон — только доступные **виды** макетов. Иначе решение
окажется заточенным под знакомые шаблоны, а на защите шаблон будет незнакомый (C6).

С change `plan-by-the-design-system` он видит и **меню дизайн-системы** шаблона:
какие её элементы (цитата, callout, стили списка) можно заказать слайду и когда они
уместны. Не координаты и не цвета — виды и назначения, как у композитора.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import Any

from deckforge.designsystem import DesignSystem
from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import InferenceClient
from deckforge.inference.structured import generate_model
from deckforge.planning.narrative import MANDATORY_FRAMES, check_narrative
from deckforge.planning.visuals import design_menu
from deckforge.planning.visuals import normalize as normalize_visual
from deckforge.planning.visuals import vocabulary as visual_vocabulary
from deckforge.registry import get_prompt_registry


class PlanningError(RuntimeError):
    """План получен, но не опирается на контент-пакет."""


#: Сколько фактов ложится на один содержательный слайд. Два — жидко, четыре — тесно
#: (предел ТЗ: шесть тезисов). Три — то, из чего получается слайд с мыслью и доводами.
FACTS_PER_SLIDE = 3

#: Ниже этого предел заголовка не опускается, каким бы тесным ни был шаблон. У VK Education
#: заголовок набирается кеглем 60 pt, и в типичную полосу помещается семь знаков — просить
#: у модели заголовок в семь знаков бессмысленно, вывода в них не поместится. На таких
#: шаблонах заголовок подрежет композиция, и это честнее, чем планировать заведомую бессмыслицу.
MIN_HEADLINE_CHARS = 25

#: Предел длины заголовка, когда шаблон его не сообщает: ни один макет не объявил
#: вместимость заголовка. Десять слов из правила 1 промпта — это примерно столько знаков.
DEFAULT_HEADLINE_CHARS = 70


#: Верх автоматического режима (Т1): целевой объём ТЗ — 10–15 слайдов. Низа нет:
#: колода на тонком материале короче, а не добита полупустыми слайдами.
AUTO_MAX_SLIDES = 15


@dataclass(frozen=True)
class SlidesDecision:
    """Сколько слайдов в колоде и почему — для отчёта прогона и интерфейса (Т1).

    `mode` — `exact`, если число задал человек, `auto`, если его подбирает план.
    `reason` — словами, для человека: число, которое тихо разошлось с заданным,
    выглядит как ошибка сервиса.
    """

    mode: str
    requested: int | None
    count: int
    reason: str


def decide_slides(
    content: ContentPackage, purpose: str, requested: int | None
) -> SlidesDecision:
    """Число слайдов в одном из двух режимов и причина.

    Задано — это потолок: материала может не хватить (см. `slides_for`), и тогда слайдов
    меньше с названной причиной. Не задано — число по материалу: факты по
    `FACTS_PER_SLIDE` на слайд плюс титул и финал, не больше `AUTO_MAX_SLIDES`.
    Снизу оба режима держит каркас назначения.
    """
    frame = len(MANDATORY_FRAMES.get(purpose, ()))
    facts = len(content.facts)
    by_content = -(-facts // FACTS_PER_SLIDE) + 2
    if requested is None:
        count = max(frame, min(AUTO_MAX_SLIDES, by_content))
        if count == AUTO_MAX_SLIDES and by_content > AUTO_MAX_SLIDES:
            why = f"материала на {by_content}, взят верх ТЗ — {AUTO_MAX_SLIDES}"
        elif count == frame and by_content < frame:
            why = f"материала на {by_content}, но каркас назначения требует {frame}"
        else:
            why = f"{facts} фактов по {FACTS_PER_SLIDE} на слайд, плюс титул и финал"
        return SlidesDecision("auto", None, count, f"подобрано автоматически: {count} — {why}")
    count = max(frame, min(requested, by_content))
    if count < requested:
        why = (
            f"задано {requested}, но материала ({facts} фактов) хватает на {count}: "
            "остальные вышли бы полупустыми"
        )
    elif count > requested:
        why = f"задано {requested}, но каркас назначения требует {count}"
    else:
        why = f"как задано: {count}"
    return SlidesDecision("exact", requested, count, why)


def slides_for(content: ContentPackage, purpose: str, requested: int | None) -> int:
    """Сколько слайдов выдержит материал.

    Целевое число из брифа — это **потолок**, а не план: на двадцати четырёх фактах
    двенадцать слайдов выходят по два факта на слайд, и композитору нечем их наполнить
    (прогон d573740bddd3: занято 10 % площади при норме 25–75). Снизу ограничивает
    каркас назначения: меньше его слайдов — это уже не презентация этого жанра.
    """
    return decide_slides(content, purpose, requested).count


def headline_chars(manifest: TemplateManifest) -> int:
    """Запасной предел заголовка: оценка шаблона по средней ширине знака.

    Оценка врёт — на VK WorkSpace обещает 46 знаков там, где помещается 27, — поэтому
    настоящий предел меряет узел графа (`pipeline/nodes/plan.py`) и передаёт его
    параметром: мерило живёт в слое вёрстки, а `planning` слой вёрстки не импортирует
    (правило 1 AGENTS.md). Эта функция остаётся для вызовов без узла — CLI и тестов.
    """
    limits = sorted(
        layout.capacity.max_chars_title
        for layout in manifest.layouts
        if layout.capacity.max_chars_title > 0
    )
    if not limits:
        return DEFAULT_HEADLINE_CHARS
    return max(MIN_HEADLINE_CHARS, limits[len(limits) // 2])


class DeckPlanner:
    """Один вызов LLM на всю колоду — бюджет 35 с (§12)."""

    def __init__(self, llm_client: InferenceClient, profile: str | None = None) -> None:
        self.llm = llm_client
        self.profile = profile

    async def plan(
        self,
        content: ContentPackage,
        manifest: TemplateManifest,
        variant: VariantProfile,
        seed: int,
        *,
        headline_limit: int | None = None,
        no_think: bool = False,
        design_system: DesignSystem | None = None,
    ) -> DeckPlan:
        """Промпт получает только *доступные виды макетов* манифеста, не сам шаблон.

        `design_system` — дизайн-система шаблона из состояния графа (DG2). По ней план
        узнаёт, какие элементы ДС можно заказать слайду и когда они уместны; заказ
        элемента, которого в ДС нет, снимается. Нет ДС — словарь прежний.

        `no_think` добавляет в запрос «/no_think» — команду семейства Qwen3 не размышлять.
        По умолчанию выключено: отключение размышлений понимают не все провайдеры,
        а на тех, кто не понимает, строка останется мусором в промпте. Нужна для замера,
        сколько из 261 с планирования приходится на размышление.
        """
        bundle = get_prompt_registry().load("deck_planner", profile=self.profile)
        brief = content.brief
        target = slides_for(content, brief.purpose, brief.target_slides)
        if brief.target_slides is None:
            # Автоматический режим (Т1): промпт называет число, которое подобрал счёт,
            # а не пустое место — «добирай до None штук» модель прочла бы как угодно.
            brief = brief.model_copy(update={"target_slides": target})
        system, user = bundle.render(
            brief=brief,
            facts=content.facts,
            datasets=content.datasets,
            variant=variant,
            seed=seed,
            language=content.brief.language,
            available_kinds=sorted({layout.kind.value for layout in manifest.layouts}),
            slides_target=target,
            facts_per_slide=FACTS_PER_SLIDE,
            headline_chars=headline_limit or headline_chars(manifest),
            visual_vocabulary=visual_vocabulary(design_system),
            design_menu=design_menu(design_system),
            no_think=no_think,
        )

        # generate_model синхронный и сам чинит невалидный ответ, сдвигая seed.
        # Свой цикл ретраев писать не надо (ARCHITECTURE.md §8).
        call = partial(
            generate_model,
            self.llm,
            DeckPlan,
            system=system,
            user=user,
            response_schema=bundle.response_schema,
            seed=seed,
            temperature=bundle.meta.temperature,
            top_p=bundle.meta.top_p,
            max_tokens=bundle.meta.max_tokens,
            # Эти поля знает код, а не модель: в схеме ответа их нет (response_omit),
            # а для валидации они нужны — подставляются до неё.
            overrides={
                "variant": variant.variant_id,
                "seed": seed,
                "language": content.brief.language,
            },
        )
        raw_plan, _completion = await asyncio.to_thread(call)
        return self._ground(raw_plan, content, variant, seed, design_system=design_system)

    def _ground(
        self,
        plan: DeckPlan,
        content: ContentPackage,
        variant: VariantProfile,
        seed: int,
        *,
        no_think: bool = False,
        design_system: DesignSystem | None = None,
    ) -> DeckPlan:
        """Привязывает план к реальности: ссылки, вариант, seed, отчёт по нарративу.

        Схема гарантирует форму, но не осмысленность: `fact_id`, которого нет
        в контент-пакете, формально валиден и сломает фактчекинг у потока C.
        """
        known_facts = {fact.fact_id for fact in content.facts}
        known_datasets = {dataset.dataset_id for dataset in content.datasets}
        known_assets = {asset.asset_id for asset in content.assets}

        slides: list[SlidePlan] = []
        dropped: list[str] = []
        bad_visuals: list[str] = []
        for slide in plan.slides:
            update: dict[str, Any] = {}
            # Заказ визуализации — единственный канал «здесь нужны показатели, здесь схема».
            # Незнакомое значение снимается: прогон 693d464d54fb, `visual: section` —
            # это вид макета, а не визуализация, и композитор печатал его в свой промпт.
            visual = normalize_visual(slide.suggested_visual, design_system)
            if visual != slide.suggested_visual:
                if slide.suggested_visual:
                    bad_visuals.append(f"{slide.slide_id}: {slide.suggested_visual}")
                update["suggested_visual"] = visual
            bad_facts = [ref for ref in slide.fact_refs if ref not in known_facts]
            if bad_facts:
                dropped.extend(bad_facts)
                update["fact_refs"] = [ref for ref in slide.fact_refs if ref in known_facts]
            if slide.dataset_ref is not None and slide.dataset_ref not in known_datasets:
                dropped.append(slide.dataset_ref)
                update["dataset_ref"] = None
            bad_assets = [ref for ref in slide.asset_refs if ref not in known_assets]
            if bad_assets:
                dropped.extend(bad_assets)
                update["asset_refs"] = [ref for ref in slide.asset_refs if ref in known_assets]
            slides.append(slide.model_copy(update=update) if update else slide)

        if not slides:
            raise PlanningError("план пуст: планировать нечего")

        narrative = check_narrative(
            plan.model_copy(update={"slides": slides}),
            purpose=content.brief.purpose,
            grouping=variant.grouping,
        )
        if bad_visuals:
            narrative = narrative.model_copy(
                update={
                    "notes": [
                        *narrative.notes,
                        "визуализация не из словаря, заказ снят: " + ", ".join(bad_visuals),
                    ]
                }
            )
        if dropped:
            unique = sorted(set(dropped))
            narrative = narrative.model_copy(
                update={
                    "notes": [
                        *narrative.notes,
                        f"модель сослалась на несуществующие идентификаторы: {', '.join(unique)}",
                    ]
                }
            )

        return plan.model_copy(
            update={
                "slides": slides,
                "variant": variant.variant_id,
                "seed": seed,
                "language": content.brief.language,
                "narrative_check": narrative,
            }
        )
