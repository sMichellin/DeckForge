"""Процесс строкой: стрелки в тексте — признак схемы `process`. Change `arrows-mean-process` (A12).

VK Tech s04, прогон d0b37773345e: «Анализ шаблона → извлечение структуры → генерация…»
легло строкой 12 pt в полосу под заголовком, а не схемой. Правило — в промптах
планировщика и композитора; если модель его не выполнила, композиция это называет.

Модель подделана: проверяется, что правило доезжает до промпта и что строка со
стрелками, оставшаяся текстом, названа в отчёте, а изменение показателя — нет.
"""

from __future__ import annotations

from typing import Any

import pytest

from deckforge.composition.composer import SlideComposer, _arrow_steps
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.planning.planner import DeckPlanner
from deckforge.registry import get_prompt_registry, load_variant_profiles
from tests.unit.test_composition import FakeLlm as ComposerLlm
from tests.unit.test_planning import PRODUCT_FRAME, payload_for
from tests.unit.test_planning import FakeLlm as PlannerLlm

#: Факт в том виде, в каком он пришёл на VK Tech s04.
PROCESS = "Анализ шаблона → извлечение структуры → генерация → аудит"


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[Fact(fact_id="f001", text=PROCESS)],
    )


def plan_slide() -> SlidePlan:
    return SlidePlan(
        slide_id="s04",
        intent=SlideIntent.PROCESS,
        headline="Колода собирается за четыре шага",
        fact_refs=["f001"],
    )


def slide_with(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {
        "slide_id": "s04",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title",
             "text": "Колода собирается за четыре шага"},
            *blocks,
        ],
    }


async def notes_for(
    payload: dict[str, Any],
    content: ContentPackage,
    manifest: TemplateManifest,
    variant: VariantProfile,
) -> list[str]:
    composer = SlideComposer(ComposerLlm(payload))
    await composer.compose(plan_slide(), content, manifest, variant, seed=1)
    return [note for note in composer.notes if "процесс строкой" in note]


# --- признак ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        PROCESS,
        "Бриф -> план -> слайды",
        "Разбор => вёрстка => проверка.",
        "Сбор данных ⟶ обучение ⟶ оценка",
    ],
)
def test_arrow_chain_is_a_process(text: str) -> None:
    assert len(_arrow_steps(text)) >= 3


@pytest.mark.parametrize(
    "text",
    [
        "Выручка выросла: 10 → 20 млн ₽",  # одна стрелка — изменение показателя
        "10 % → 20 % → 30 %",  # ход показателя, а не шаги работы
        "Шаблон → ",  # висячая стрелка
        "Шаблон разбирается, затем верстается",  # порядок словами — забота промпта
    ],
)
def test_change_of_a_value_is_not_a_process(text: str) -> None:
    assert _arrow_steps(text) == []


# --- промпты -------------------------------------------------------------------------


def test_active_prompts_carry_the_arrow_rule() -> None:
    """Правило живёт в активной версии обоих промптов, а не в старой."""
    registry = get_prompt_registry()
    planner = registry.load("deck_planner")
    composer = registry.load("slide_composer")

    assert planner.version != "1.0.0" and composer.version != "1.0.0"
    assert "соединены стрелками" in planner.system_template
    assert "Стрелки в тексте — это процесс" in composer.system_template


async def test_planner_prompt_names_arrows_as_a_process(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    llm = PlannerLlm(payload_for(PRODUCT_FRAME))
    await DeckPlanner(llm).plan(content, manifest, variant_a, seed=1)

    prompt = llm.prompt_text
    assert "соединены стрелками" in prompt
    assert "«А → Б → В»), заказывает" in prompt
    assert PROCESS in prompt, "факт со стрелками не дошёл до планировщика"


async def test_composer_prompt_asks_for_a_process_diagram(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    llm = ComposerLlm(slide_with())
    await SlideComposer(llm).compose(plan_slide(), content, manifest, variant_a, seed=1)

    assert "Стрелки в тексте — это процесс" in llm.prompt
    assert "со стрелками в текст слайда не ставь" in " ".join(llm.prompt.split())


# --- заметка композиции --------------------------------------------------------------


async def test_process_left_as_a_text_line_is_named(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Нарушитель: s04 VK Tech — строка со стрелками в текстовом блоке, схемы нет."""
    payload = slide_with(
        {"block_id": "b2", "type": "text", "placeholder_idx": 1, "role": "body",
         "text": PROCESS}
    )
    notes = await notes_for(payload, content, manifest, variant_a)

    assert len(notes) == 1
    assert "слайд s04: текст b2" in notes[0]
    assert "шагов 4" in notes[0] and "схему process" in notes[0]


async def test_process_hidden_in_a_bullet_is_named(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    payload = slide_with(
        {"block_id": "b2", "type": "bullets", "placeholder_idx": 1,
         "items": [{"text": "Система работает автоматически"}, {"text": PROCESS}]}
    )
    assert len(await notes_for(payload, content, manifest, variant_a)) == 1


async def test_process_drawn_as_a_diagram_is_not_named(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: модель выполнила правило — схема `process`, рядом вывод без стрелок."""
    payload = slide_with(
        {"block_id": "b2", "type": "smartart", "pattern": "process",
         "items": ["Анализ шаблона", "Извлечение структуры", "Генерация", "Аудит"]},
        {"block_id": "b3", "type": "text", "placeholder_idx": 1, "role": "body",
         "text": "Каждый шаг проверяется до следующего"},
    )
    assert await notes_for(payload, content, manifest, variant_a) == []


async def test_value_change_in_text_is_not_named(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: одна стрелка между значениями — это изменение показателя, текстом ему и место."""
    payload = slide_with(
        {"block_id": "b2", "type": "text", "placeholder_idx": 1, "role": "body",
         "text": "Время сборки колоды сократилось: 40 → 5 минут"}
    )
    assert await notes_for(payload, content, manifest, variant_a) == []


async def test_arrows_in_the_headline_are_not_named(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Заголовок о порядке — вывод, а не сам порядок: схема под ним, не вместо него."""
    payload = {
        "slide_id": "s04", "layout_id": "L07", "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title",
             "text": "Шаблон → структура → колода"},
            {"block_id": "b2", "type": "text", "placeholder_idx": 1, "role": "body",
             "text": "Четыре шага без ручной вёрстки"},
        ],
    }
    assert await notes_for(payload, content, manifest, variant_a) == []
