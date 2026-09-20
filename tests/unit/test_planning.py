"""План колоды. Change (10) `deck-planning`.

Модель подделана: проверяется не качество формулировок, а то, что план привязан
к контент-пакету и что нарушения нарратива называются, а не замалчиваются.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deckforge.domain.content import Brief, ContentPackage, Fact, Number
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import DeckPlan
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import Completion
from deckforge.planning.narrative import (
    MANDATORY_FRAMES,
    MAX_HEADLINE_WORDS,
    check_narrative,
)
from deckforge.planning.planner import DeckPlanner, PlanningError
from deckforge.registry import load_variant_profiles


class FakeLlm:
    """Отдаёт заранее заготовленный JSON и запоминает, что ему прислали."""

    model = "fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.messages: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        self.messages = messages
        return Completion(text=json.dumps(self.payload, ensure_ascii=False), model=self.model)

    @property
    def prompt_text(self) -> str:
        return "\n".join(str(m.get("content", "")) for m in self.messages)


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(
            purpose="product",
            audience="правление компании",
            target_slides=6,
            language="ru",
            tone="деловой, без маркетинговых обещаний",
            key_message="Платформа вышла на окупаемость, инвестиции идут в масштабирование",
        ),
        facts=[
            Fact(
                fact_id="f001",
                text="Выручка выросла на 37,5 %",
                numbers=[Number(value=37.5, unit="%", raw="37,5 %")],
            ),
            Fact(fact_id="f002", text="Клиентов стало более 500"),
        ],
    )


@pytest.fixture
def variant_c() -> VariantProfile:
    return load_variant_profiles()["C"]


def payload_for(intents: list[SlideIntent], headline: str = "Выручка выросла на 37 % за год",
                fact_refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "deck_id": "d1",
        "variant": "A",
        "seed": 1,
        "language": "ru",
        "slides": [
            {
                "slide_id": f"s{i:02d}",
                "intent": intent.value,
                "headline": headline,
                "fact_refs": fact_refs if fact_refs is not None else ["f001"],
            }
            for i, intent in enumerate(intents, start=1)
        ],
    }


PRODUCT_FRAME = list(MANDATORY_FRAMES["product"])


# ------------------------------------------------------------------ планировщик


@pytest.mark.asyncio
async def test_plan_is_bound_to_the_variant_and_seed(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Вариант и seed задаёт пайплайн, а не модель: иначе повтор прогона не воспроизводится."""
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    plan = await DeckPlanner(llm).plan(content, manifest, variant_c, seed=777)

    assert plan.variant == "C"
    assert plan.seed == 777


@pytest.mark.asyncio
async def test_dangling_references_are_dropped_and_reported(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """f999 в контент-пакете нет. Схема такой ответ пропускает, фактчекинг потока C — нет."""
    llm = FakeLlm(payload_for(PRODUCT_FRAME, fact_refs=["f001", "f999"]))
    plan = await DeckPlanner(llm).plan(content, manifest, variant_c, seed=1)

    assert all("f999" not in slide.fact_refs for slide in plan.slides)
    assert any("f999" in note for note in plan.narrative_check.notes)


@pytest.mark.asyncio
async def test_empty_plan_is_refused(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    llm = FakeLlm({"deck_id": "d1", "variant": "A", "seed": 1, "slides": []})
    with pytest.raises((PlanningError, Exception)):
        await DeckPlanner(llm).plan(content, manifest, variant_c, seed=1)


@pytest.mark.asyncio
async def test_prompt_carries_brief_and_available_kinds_but_not_the_template(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Планировщик не должен знать, что внутри файла шаблона (C6)."""
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    await DeckPlanner(llm).plan(content, manifest, variant_c, seed=1)

    prompt = llm.prompt_text
    assert "правление компании" in prompt
    assert "деловой, без маркетинговых обещаний" in prompt
    assert "инвестиции идут в масштабирование" in prompt
    assert "title" in prompt and "bullets" in prompt
    assert manifest.source_name not in prompt
    assert "Заголовок и содержимое" not in prompt, "имя макета шаблона в промпт не уходит"


# --------------------------------------------------------------------- нарратив


def test_frame_violation_is_named() -> None:
    plan = DeckPlan.model_validate(
        payload_for([SlideIntent.TITLE, SlideIntent.EVIDENCE, SlideIntent.CLOSING])
    )
    check = check_narrative(plan, purpose="product", grouping="by_topic")

    assert not check.has_arc
    assert any("каркас" in note for note in check.notes)


def test_correct_frame_passes() -> None:
    plan = DeckPlan.model_validate(payload_for(PRODUCT_FRAME))
    check = check_narrative(plan, purpose="product", grouping="by_topic")

    assert check.has_arc
    assert check.notes == []


def test_long_headline_is_caught() -> None:
    long = " ".join(["слово"] * (MAX_HEADLINE_WORDS + 1))
    plan = DeckPlan.model_validate(payload_for(PRODUCT_FRAME, headline=long))
    check = check_narrative(plan, purpose="product")

    assert not check.one_idea_per_slide
    assert any("длиннее" in note for note in check.notes)


def test_one_role_may_not_take_more_than_half_the_deck() -> None:
    intents = [SlideIntent.TITLE, *[SlideIntent.EVIDENCE] * 4, SlideIntent.CLOSING]
    plan = DeckPlan.model_validate(payload_for(intents))
    check = check_narrative(plan, purpose=None)

    assert any("evidence" in note and "%" in note for note in check.notes)


def test_pyramid_requires_the_conclusion_up_front() -> None:
    late = [
        SlideIntent.TITLE,
        SlideIntent.PROBLEM,
        SlideIntent.EVIDENCE,
        SlideIntent.METRICS,
        SlideIntent.SOLUTION,
        SlideIntent.CLOSING,
    ]
    assert any("пирамид" in n for n in check_narrative(
        DeckPlan.model_validate(payload_for(late)), grouping="pyramid").notes)

    early = [
        SlideIntent.TITLE,
        SlideIntent.SUMMARY,
        SlideIntent.PROBLEM,
        SlideIntent.EVIDENCE,
        SlideIntent.CLOSING,
    ]
    assert not any("пирамид" in n for n in check_narrative(
        DeckPlan.model_validate(payload_for(early)), grouping="pyramid").notes)


def test_narrative_arc_does_not_demand_the_pyramid() -> None:
    """Иначе ось различий вариантов схлопывается, и B перестаёт отличаться от C (C7)."""
    late = [
        SlideIntent.TITLE,
        SlideIntent.PROBLEM,
        SlideIntent.EVIDENCE,
        SlideIntent.SOLUTION,
        SlideIntent.CLOSING,
    ]
    check = check_narrative(DeckPlan.model_validate(payload_for(late)), grouping="by_narrative_arc")
    assert not any("пирамид" in note for note in check.notes)


def test_deck_without_a_conclusion_is_reported() -> None:
    intents = [SlideIntent.TITLE, SlideIntent.PROBLEM, SlideIntent.EVIDENCE, SlideIntent.CLOSING]
    check = check_narrative(DeckPlan.model_validate(payload_for(intents)))

    assert not check.has_arc
    assert any("главным выводом" in note for note in check.notes)


def test_every_purpose_of_the_brief_has_a_frame() -> None:
    """Пять назначений ТЗ: фича, продукт, проект, инициатива, отчёт."""
    assert set(MANDATORY_FRAMES) == {"feature", "product", "project", "initiative", "report"}
    for frame in MANDATORY_FRAMES.values():
        assert frame[0] == SlideIntent.TITLE
        assert frame[-1] == SlideIntent.CLOSING


@pytest.mark.asyncio
async def test_no_think_reaches_the_prompt_only_when_asked(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Команду понимают не все провайдеры: по умолчанию её в промпте быть не должно."""
    quiet = FakeLlm(payload_for(PRODUCT_FRAME))
    await DeckPlanner(quiet).plan(content, manifest, variant_c, seed=1)
    assert "/no_think" not in quiet.prompt_text

    fast = FakeLlm(payload_for(PRODUCT_FRAME))
    await DeckPlanner(fast).plan(content, manifest, variant_c, seed=1, no_think=True)
    assert "/no_think" in fast.prompt_text


@pytest.mark.asyncio
async def test_models_wrong_variant_does_not_burn_the_repairs(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Прогон 59e0014d2fdc: модель трижды прислала `variant: "report"`, и план упал.

    Вариант пайплайну известен заранее — чужое значение модели заменяется до валидации.
    """
    payload = payload_for(PRODUCT_FRAME) | {"variant": "report", "seed": "не число"}
    plan = await DeckPlanner(FakeLlm(payload)).plan(content, manifest, variant_c, seed=5)
    assert (plan.variant, plan.seed) == ("C", 5)


@pytest.mark.asyncio
async def test_plan_without_code_owned_fields_is_accepted(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Схема ответа их больше не просит — ответ без них законен."""
    payload = {k: v for k, v in payload_for(PRODUCT_FRAME).items() if k in ("deck_id", "slides")}
    plan = await DeckPlanner(FakeLlm(payload)).plan(content, manifest, variant_c, seed=5)
    assert plan.variant == "C" and plan.language == content.brief.language


def test_planner_is_not_asked_for_fields_the_code_fills() -> None:
    import json as _json

    from deckforge.config import PROMPTS_DIR

    schema = _json.loads(
        (PROMPTS_DIR / "deck_planner" / "1.0.0" / "schema.json").read_text(encoding="utf-8")
    )
    assert set(schema["properties"]) == {"deck_id", "slides"}


# --- сколько слайдов выдержит материал ----------------------------------------


def test_thin_content_gets_fewer_slides_than_requested() -> None:
    """Прогон d573740bddd3: 24 факта на 12 слайдов — занято 10 % площади при норме 25–75."""
    from deckforge.domain.content import Fact
    from deckforge.planning.planner import slides_for

    thin = ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=12),
        facts=[Fact(fact_id=f"f{i:03d}", text=f"Факт {i}") for i in range(1, 25)],
    )
    assert slides_for(thin, "product", 12) == 10


def test_rich_content_does_not_exceed_the_brief() -> None:
    """Целевое число из брифа — потолок: автор просил столько, сколько просил."""
    from deckforge.domain.content import Fact
    from deckforge.planning.planner import slides_for

    rich = ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=12),
        facts=[Fact(fact_id=f"f{i:03d}", text=f"Факт {i}") for i in range(1, 100)],
    )
    assert slides_for(rich, "product", 12) == 12


def test_frame_is_the_floor_however_thin_the_content() -> None:
    """Ниже каркаса назначения опускаться нельзя: это уже не презентация этого жанра."""
    from deckforge.planning.narrative import MANDATORY_FRAMES
    from deckforge.planning.planner import slides_for

    almost_empty = ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=12)
    )
    assert slides_for(almost_empty, "product", 12) == len(MANDATORY_FRAMES["product"])


def test_planner_uses_the_limit_the_node_measured(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Мерило живёт в слое вёрстки, а `planning` его не импортирует (правило 1).

    Узел графа меряет предел и передаёт параметром; промпт печатает именно его.
    """
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    asyncio.run(DeckPlanner(llm).plan(content, manifest, variant_c, seed=1, headline_limit=27))

    assert "27 знаков" in llm.prompt_text


def test_headline_limit_never_drops_below_a_usable_length() -> None:
    """У VK Education заголовок кеглем 60 pt: в полосу влезает семь знаков.

    Просить у модели вывод в семь знаков бессмысленно — там подрежет композиция.
    """
    from deckforge.domain.template import TemplateManifest as TM
    from deckforge.planning.planner import (
        DEFAULT_HEADLINE_CHARS,
        MIN_HEADLINE_CHARS,
        headline_chars,
    )

    assert MIN_HEADLINE_CHARS >= 25
    # Шаблон, который о заголовке молчит вовсе: остаётся умолчание.
    assert headline_chars(TM.model_construct(layouts=[])) == DEFAULT_HEADLINE_CHARS


# --- переписывание заголовков, которые не уместились -------------------------


def plan_with(*headlines: str) -> DeckPlan:
    from deckforge.domain.plan import SlidePlan

    return DeckPlan(
        deck_id="d1",
        variant="A",
        seed=1,
        slides=[
            SlidePlan(
                slide_id=f"s{i:02d}",
                intent=SlideIntent.PROBLEM,
                headline=headline,
                fact_refs=["f001"],
            )
            for i, headline in enumerate(headlines, start=1)
        ],
    )


def shorter_than(limit: int):
    """Мерило узла графа, подделанное длиной: слой планирования о рамках не знает."""
    return lambda text: len(text) <= limit


def rewrite(plan: DeckPlan, content: ContentPackage, llm: Any, limit: int = 27) -> Any:
    from deckforge.planning.headlines import HeadlineRewriter

    rewriter = HeadlineRewriter(llm)
    out = asyncio.run(
        rewriter.rewrite_overlong(
            plan, content, fits=shorter_than(limit), limit=limit, seed=1
        )
    )
    return out, rewriter


def test_headline_that_did_not_fit_is_rewritten_not_trimmed(content: ContentPackage) -> None:
    """Прогон ea732e59510c: 9 заголовков из 10 длиннее рамки, все обрезаны многоточием.

    Обрубок теряет вывод, ради которого заголовок и писался, — переписывает модель.
    """
    llm = FakeLlm({"headline": "Выручка выросла на 37 %"})
    plan = plan_with("Выручка выросла на 37 % за счёт корпоративных клиентов")
    out, rewriter = rewrite(plan, content, llm)

    assert out.slides[0].headline == "Выручка выросла на 37 %"
    assert any("переписан под рамку" in note for note in rewriter.notes)


def test_headline_that_fits_is_not_touched(content: ContentPackage) -> None:
    """Лишний вызов модели на слайд — это время прогона, потраченное впустую."""
    llm = FakeLlm({"headline": "Что-то другое"})
    out, rewriter = rewrite(plan_with("Выручка выросла на 37 %"), content, llm)

    assert out.slides[0].headline == "Выручка выросла на 37 %"
    assert llm.messages == [], "модель звали, хотя заголовок помещался"
    assert rewriter.notes == []


def test_rewrite_that_is_no_shorter_keeps_the_original(content: ContentPackage) -> None:
    """Менять один длинный заголовок на другой длинный незачем: исходный хотя бы по фактам."""
    long_headline = "Выручка выросла на 37 % за счёт корпоративных клиентов"
    llm = FakeLlm({"headline": long_headline + " и новых рынков"})
    out, rewriter = rewrite(plan_with(long_headline), content, llm)

    assert out.slides[0].headline == long_headline
    assert any("не короче исходного" in note for note in rewriter.notes)


def test_model_failure_does_not_break_the_run(content: ContentPackage) -> None:
    """Заголовок длиннее рамки — не отказ прогона: колода соберётся и с подрезанным."""
    from deckforge.inference.client import InferenceError

    class Broken:
        model = "fake"

        def complete(self, *_: Any, **__: Any) -> Completion:
            raise InferenceError("сервер не ответил")

    long_headline = "Выручка выросла на 37 % за счёт корпоративных клиентов"
    out, rewriter = rewrite(plan_with(long_headline), content, Broken())

    assert out.slides[0].headline == long_headline
    assert any("не переписала заголовок" in note for note in rewriter.notes)


# --- заказ визуализации ------------------------------------------------------


def test_layout_kind_in_suggested_visual_is_dropped(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Прогон 693d464d54fb: `visual: section` на восьми слайдах из десяти.

    Это вид макета, а не визуализация: поле в промпте не объяснено, и модель заполняла
    его словарём, который видела рядом. Композитор печатал мусор в свой промпт.
    """
    payload = payload_for(PRODUCT_FRAME)
    for slide in payload["slides"]:
        slide["suggested_visual"] = "section"
    plan = asyncio.run(
        DeckPlanner(FakeLlm(payload)).plan(content, manifest, variant_c, seed=1)
    )

    assert {s.suggested_visual for s in plan.slides} == {None}
    assert any("визуализация не из словаря" in n for n in plan.narrative_check.notes)


def test_visual_from_the_vocabulary_survives(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    payload = payload_for(PRODUCT_FRAME)
    payload["slides"][0]["suggested_visual"] = "kpi"
    payload["slides"][1]["suggested_visual"] = "smartart:process"
    plan = asyncio.run(
        DeckPlanner(FakeLlm(payload)).plan(content, manifest, variant_c, seed=1)
    )

    assert [plan.slides[0].suggested_visual, plan.slides[1].suggested_visual] == [
        "kpi",
        "smartart:process",
    ]
    assert not any("визуализация не из словаря" in n for n in plan.narrative_check.notes)


def test_vocabulary_is_built_from_domain_enums_not_literals() -> None:
    """Новый тип диаграммы обязан попадать в словарь сам, без правки кода словаря."""
    from deckforge.domain.enums import ChartType, SmartArtPattern
    from deckforge.planning.visuals import vocabulary

    words = set(vocabulary())
    assert {f"chart:{item.value}" for item in ChartType} <= words
    assert {f"smartart:{item.value}" for item in SmartArtPattern} <= words


def test_planner_prompt_names_the_vocabulary(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Поле, которое в промпте не объяснено, модель заполняет чем попало."""
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    asyncio.run(DeckPlanner(llm).plan(content, manifest, variant_c, seed=1))

    assert "suggested_visual" in llm.prompt_text
    assert "smartart:process" in llm.prompt_text


def test_prompt_names_the_signs_of_a_process_not_just_the_word(
    content: ContentPackage, manifest: TemplateManifest, variant_c: VariantProfile
) -> None:
    """Прогоны 2ac85990b2f2 и 34272d11db06: визуализация не заказана ни разу.

    Материал при этом описан процессом (f003–f007 `task_desription.md`), но «этапы» —
    это понятие, а не признак: модель искала слово, не находила и молчала.
    """
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    asyncio.run(DeckPlanner(llm).plan(content, manifest, variant_c, seed=1))

    prompt = llm.prompt_text
    assert "неопределённой форме" in prompt, "признак последовательности не назван"
    assert "сначала" in prompt and "затем" in prompt
    assert "ЭТОГО слайда" in prompt, "kpi заказывается по числам всей колоды"
