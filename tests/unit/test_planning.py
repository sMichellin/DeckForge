"""План колоды. Change (10) `deck-planning`.

Модель подделана: проверяется не качество формулировок, а то, что план привязан
к контент-пакету и что нарушения нарратива называются, а не замалчиваются.
"""

from __future__ import annotations

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
