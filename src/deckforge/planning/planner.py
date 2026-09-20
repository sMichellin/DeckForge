"""Состав и порядок слайдов. Change (10) `deck-planning`.

Заголовок обязан быть **выводом**, а не темой: требование закладывается в промпт
`deck_planner`, а не чинится авто-фиксом после.

Планировщик не видит шаблон — только доступные **виды** макетов. Иначе решение
окажется заточенным под знакомые шаблоны, а на защите шаблон будет незнакомый (C6).
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import InferenceClient
from deckforge.inference.structured import generate_model
from deckforge.planning.narrative import MANDATORY_FRAMES, check_narrative
from deckforge.registry import get_prompt_registry


class PlanningError(RuntimeError):
    """План получен, но не опирается на контент-пакет."""


#: Сколько фактов ложится на один содержательный слайд. Два — жидко, четыре — тесно
#: (предел ТЗ: шесть тезисов). Три — то, из чего получается слайд с мыслью и доводами.
FACTS_PER_SLIDE = 3

#: Предел длины заголовка, когда шаблон его не сообщает: ни один макет не объявил
#: вместимость заголовка. Десять слов из правила 1 промпта — это примерно столько знаков.
DEFAULT_HEADLINE_CHARS = 70


def slides_for(content: ContentPackage, purpose: str, requested: int) -> int:
    """Сколько слайдов выдержит материал.

    Целевое число из брифа — это **потолок**, а не план: на двадцати четырёх фактах
    двенадцать слайдов выходят по два факта на слайд, и композитору нечем их наполнить
    (прогон d573740bddd3: занято 10 % площади при норме 25–75). Снизу ограничивает
    каркас назначения: меньше его слайдов — это уже не презентация этого жанра.
    """
    frame = MANDATORY_FRAMES.get(purpose, ())
    structural = 2  # титул и финал: фактов не несут
    by_content = -(-len(content.facts) // FACTS_PER_SLIDE) + structural
    return max(len(frame), min(requested, by_content))


def headline_chars(manifest: TemplateManifest) -> int:
    """Сколько знаков заголовка держит самый тесный макет шаблона.

    Планировщик макета ещё не знает, поэтому ориентируется на тесный: заголовок,
    который не влез, обрывается многоточием уже при вёрстке (прогон d573740bddd3,
    12 заголовков из 12).
    """
    limits = [
        layout.capacity.max_chars_title
        for layout in manifest.layouts
        if layout.capacity.max_chars_title > 0
    ]
    return min(limits) if limits else DEFAULT_HEADLINE_CHARS


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
        no_think: bool = False,
    ) -> DeckPlan:
        """Промпт получает только *доступные виды макетов* манифеста, не сам шаблон.

        `no_think` добавляет в запрос «/no_think» — команду семейства Qwen3 не размышлять.
        По умолчанию выключено: отключение размышлений понимают не все провайдеры,
        а на тех, кто не понимает, строка останется мусором в промпте. Нужна для замера,
        сколько из 261 с планирования приходится на размышление.
        """
        bundle = get_prompt_registry().load("deck_planner", profile=self.profile)
        system, user = bundle.render(
            brief=content.brief,
            facts=content.facts,
            datasets=content.datasets,
            variant=variant,
            seed=seed,
            language=content.brief.language,
            available_kinds=sorted({layout.kind.value for layout in manifest.layouts}),
            slides_target=slides_for(content, content.brief.purpose, content.brief.target_slides),
            facts_per_slide=FACTS_PER_SLIDE,
            headline_chars=headline_chars(manifest),
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
        return self._ground(raw_plan, content, variant, seed)

    def _ground(
        self,
        plan: DeckPlan,
        content: ContentPackage,
        variant: VariantProfile,
        seed: int,
        *,
        no_think: bool = False,
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
        for slide in plan.slides:
            update: dict[str, Any] = {}
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
