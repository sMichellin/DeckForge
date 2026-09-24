"""Композитор не берёт от модели рецепт, зону и отчёт о вписывании.

Change `composer-does-not-name-the-recipe`, таск RG1 зонтичного предложения
`recipe-is-not-the-models-word` (`docs/agents/tasks-24-09.md`).

Регрессия 24.09: пять прогонов на ml110 упали на стадии `render` с `KeyError` по
идентификатору блока. `slide-recipes` добавил `recipe_id` и `zone_id` в `SlideIR`,
а `SlideIR` — это ещё и схема ответа промпта `slide_composer`; в `response_omit` они
не попали, и модель их заполняла. Закрывающему слайду рецепт не достаётся (у шаблона
кейса нет вида `final`), `bind_to_recipe` выдумку не перезаписывает — и `recipe_id`
вида `L12_15_title_slide_closing_step_a` уезжает в колоду как факт.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deckforge.composition.composer import SlideComposer
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import Completion
from deckforge.pipeline.nodes.fit import _fit_shortening
from deckforge.registry import load_variant_profiles


class FakeLlm:
    model = "fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        return Completion(text=json.dumps(self.payload, ensure_ascii=False), model=self.model)


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[Fact(fact_id="f001", text="Выручка выросла на 37,5 %")],
    )


def closing_slide() -> SlidePlan:
    """Закрывающий слайд — то самое место, где рецепт не достаётся."""
    return SlidePlan(
        slide_id="s10",
        intent=SlideIntent.CLOSING,
        headline="Спасибо",
        fact_refs=["f001"],
    )


#: Ответ модели из прогона `b5babbdac83f`, слайд `s10`: придуманный рецепт и придуманные
#: зоны. Идентификаторы блоков — те, по которым падала запись.
INVENTED = {
    "blocks": [
        {"block_id": "b1", "type": "text", "role": "title", "zone_id": "title",
         "text": "Спасибо за внимание"},
        {"block_id": "b2", "type": "text", "role": "body", "zone_id": "body",
         "text": "Вопросы и обсуждение"},
    ],
    "recipe_id": "L12_15_title_slide_closing_step_a",
}


async def test_recipe_and_zones_named_by_the_model_are_dropped(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    composer = SlideComposer(FakeLlm(INVENTED))
    ir = await composer.compose(closing_slide(), content, manifest, variant_a, seed=2001)

    assert ir.recipe_id is None, "рецепт от модели остался в IR"
    assert all(block.zone_id is None for block in ir.blocks), "зона от модели осталась в IR"
    assert ir.fit_report == {}


async def test_every_block_keeps_a_place(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Снятие зоны не должно оставить блок без места: ни плейсхолдера, ни координат.

    Страховка инварианта, а не воспроизведение регрессии: блок без `placeholder_idx`
    и так уходит решателю (`_bind`, ветка «координатам модели не доверяем вовсе»).
    """
    ir = await SlideComposer(FakeLlm(INVENTED)).compose(
        closing_slide(), content, manifest, variant_a, seed=2001
    )

    assert [block.block_id for block in ir.blocks] == ["b1", "b2"]
    assert all(
        block.placeholder_idx is not None or block.bbox is not None for block in ir.blocks
    ), "блок остался без места: ни плейсхолдера, ни координат"


async def test_the_slide_is_no_longer_skipped_by_fitting(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Вот где ломалось: `fit` пропускает слайд по `recipe_id`, и отчёт остаётся пустым.

    Писатель берёт кегль как `slide_ir.fit_report[block.block_id]` — прямым обращением,
    и на пустом отчёте это `KeyError 'b1'`, ровно тот, что положил пять прогонов.
    Пока `recipe_id` от модели цел, слайд мимо вписывания и проходит.
    """
    ir = await SlideComposer(FakeLlm(INVENTED)).compose(
        closing_slide(), content, manifest, variant_a, seed=2001
    )

    fitted, _notes = _fit_shortening(ir, manifest, None, content)
    missing = {block.block_id for block in fitted.blocks} - set(fitted.fit_report)
    assert not missing, f"вписывание не посчитало кегль для {sorted(missing)}"


async def test_what_the_model_named_is_reported(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Молча снять — значит потерять след: отчёт прогона обязан назвать выдумку."""
    composer = SlideComposer(FakeLlm(INVENTED))
    await composer.compose(closing_slide(), content, manifest, variant_a, seed=2001)

    named = [note for note in composer.notes if "L12_15_title_slide_closing_step_a" in note]
    assert named, f"выдумка модели не названа в отчёте: {composer.notes}"
    assert "title" in named[0] and "body" in named[0], "зоны не названы"


async def test_fit_report_from_the_model_is_dropped(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    payload = {
        "blocks": [
            {"block_id": "b1", "type": "text", "role": "title", "placeholder_idx": 0,
             "text": "Заголовок"}
        ],
        "fit_report": {
            "b1": {"final_size_pt": 96, "lines": 1, "overflow": False, "strategy": "as_is"}
        },
    }
    composer = SlideComposer(FakeLlm(payload))
    ir = await composer.compose(closing_slide(), content, manifest, variant_a, seed=1)

    assert ir.fit_report == {}, "замер от модели принят за свой"
    assert any("отчёт о вписывании" in note for note in composer.notes)


async def test_a_clean_answer_is_not_touched_and_not_reported(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Ответ без полей каталога проходит как прежде — и оговорки о нём нет."""
    payload = {
        "blocks": [
            {"block_id": "b1", "type": "text", "role": "title", "placeholder_idx": 0,
             "text": "Заголовок"}
        ]
    }
    composer = SlideComposer(FakeLlm(payload))
    ir = await composer.compose(closing_slide(), content, manifest, variant_a, seed=1)

    assert ir.recipe_id is None and ir.fit_report == {}
    assert not any("каталог композиций" in note for note in composer.notes)
