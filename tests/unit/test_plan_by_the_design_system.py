"""План заказывает элементы дизайн-системы шаблона. Change `plan-by-the-design-system`.

Что проверяется:

* словарь заказа: без ДС — прежний, с ДС — плюс её элементы, и только те, что в ДС есть;
* планировщик: меню ДС с назначениями уходит в промпт, заказ элемента ДС переживает
  привязку плана, заказ элемента, которого у шаблона нет, снимается с заметкой;
* композитор: заказ элемента ДС выполнен, только если выполнен тот самый вид —
  callout «риск» не выполняет заказ «инсайта», маркированный список — иконочного;
* граф: ДС из узла `parse` доходит до промпта планировщика (сквозной прогон на подделке).

Шаблоны — синтетический манифест `conftest` и стандартный шаблон python-pptx (C6).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from deckforge.composition.composer import SlideComposer, _fulfils
from deckforge.config import RunConfig
from deckforge.designsystem import DesignSystem, derive
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    CalloutBlock,
    QuoteBlock,
    SmartArtBlock,
)
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import Completion
from deckforge.parsing import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.run import collect_content_paths, generate_variant, load_brief
from deckforge.planning.planner import DeckPlanner
from deckforge.planning.visuals import DESIGN_ORDERS, design_menu, normalize, vocabulary
from deckforge.registry import get_prompt_registry, load_variant_profiles
from tests.integration.test_native_objects import build_template
from tests.integration.test_pipeline_end_to_end import FakeInference, theme_fonts
from tests.unit.test_compose_by_the_design_system import TITLE
from tests.unit.test_compose_by_the_design_system import FakeLlm as ComposerLlm
from tests.unit.test_planning import PRODUCT_FRAME, FakeLlm, payload_for


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[
            Fact(fact_id="f001", text="Выручка выросла на 37,5 % за год"),
            Fact(fact_id="f002", text="«Шаблон задаёт язык колоды», — сказал автор брифа"),
        ],
    )


@pytest.fixture
def design(manifest: TemplateManifest) -> DesignSystem:
    return derive(manifest)


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    """Шаблон, материалы и бриф сквозного прогона — те же, что в `test_pipeline_end_to_end`.

    Своя фикстура, а не импорт чужой: импортированная фикстура в параметре теста —
    это переопределение имени, и ruff CI на нём падает (F811).
    """
    content = tmp_path / "content"
    content.mkdir()
    (content / "факты.md").write_text(
        "# Итоги года\n\nВыручка выросла на 37,5 % за год.\n\nКлиентов стало более 500.\n",
        encoding="utf-8",
    )
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        "purpose: product\naudience: правление\ntarget_slides: 6\nlanguage: ru\n",
        encoding="utf-8",
    )
    return {
        "template": build_template(tmp_path / "template.pptx"),
        "content": content,
        "brief": brief,
        "root": tmp_path,
    }


def without(ds: DesignSystem, *kinds: str) -> DesignSystem:
    """ДС, в которой этих элементов нет: так выглядит шаблон, который их не рисует."""
    kept = [item for item in ds.synthesized if item.kind not in kinds]
    return ds.model_copy(update={"synthesized": kept})


# --- словарь ------------------------------------------------------------------------


def test_without_a_design_system_the_vocabulary_is_unchanged() -> None:
    """CLI и тесты без графа зовут словарь без ДС — он обязан остаться прежним."""
    words = set(vocabulary())
    assert not words & set(DESIGN_ORDERS)
    assert {"kpi", "table", "image", "chart", "smartart", "smartart:process"} <= words


def test_the_design_system_opens_its_elements_to_the_plan(design: DesignSystem) -> None:
    menu = design_menu(design)

    assert [item.order for item in menu] == list(DESIGN_ORDERS)
    assert set(DESIGN_ORDERS) <= set(vocabulary(design))
    # Назначение — из самой ДС, тем же текстом, что на её странице.
    purposes = {item.kind: item.purpose for item in design.synthesized}
    for item in menu:
        assert item.purpose == purposes[DESIGN_ORDERS[item.order]]


def test_an_element_the_template_lacks_is_not_on_the_menu(design: DesignSystem) -> None:
    """Нарушитель: заказ на то, чего шаблон не нарисует. Он снимается, как «section»."""
    poor = without(design, "callout_risk", "quote")

    assert "callout:risk" not in vocabulary(poor)
    assert normalize("callout:risk", poor) is None
    assert normalize("quote", poor) is None
    assert normalize(" Callout:Insight ", poor) == "callout:insight"


# --- планировщик ----------------------------------------------------------------------


def test_the_planner_prompt_lists_the_menu_with_purposes(
    content: ContentPackage,
    manifest: TemplateManifest,
    variant_a: VariantProfile,
    design: DesignSystem,
) -> None:
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    asyncio.run(DeckPlanner(llm).plan(content, manifest, variant_a, seed=1, design_system=design))

    for item in design_menu(design):
        assert f"`{item.order}`" in llm.prompt_text
    risk = next(item for item in design.synthesized if item.kind == "callout_risk")
    assert risk.purpose[1:] in llm.prompt_text


def test_without_a_design_system_the_planner_prompt_has_no_menu(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    asyncio.run(DeckPlanner(llm).plan(content, manifest, variant_a, seed=1))

    assert "элементы дизайн-системы этого шаблона" not in llm.prompt_text
    assert "callout:insight" not in llm.prompt_text


def test_design_orders_survive_the_grounding(
    content: ContentPackage,
    manifest: TemplateManifest,
    variant_a: VariantProfile,
    design: DesignSystem,
) -> None:
    payload = payload_for(PRODUCT_FRAME)
    orders = ["quote", "callout:risk", "bullets:icon", "bullets:numbered"]
    for slide, order in zip(payload["slides"], orders, strict=False):
        slide["suggested_visual"] = order
    plan = asyncio.run(
        DeckPlanner(FakeLlm(payload)).plan(
            content, manifest, variant_a, seed=1, design_system=design
        )
    )

    assert [slide.suggested_visual for slide in plan.slides[:4]] == orders
    assert not any("не из словаря" in note for note in plan.narrative_check.notes)


def test_an_order_the_template_cannot_draw_is_dropped_with_a_note(
    content: ContentPackage,
    manifest: TemplateManifest,
    variant_a: VariantProfile,
    design: DesignSystem,
) -> None:
    payload = payload_for(PRODUCT_FRAME)
    payload["slides"][1]["suggested_visual"] = "callout:risk"
    plan = asyncio.run(
        DeckPlanner(FakeLlm(payload)).plan(
            content, manifest, variant_a, seed=1, design_system=without(design, "callout_risk")
        )
    )

    assert plan.slides[1].suggested_visual is None
    assert any("callout:risk" in note for note in plan.narrative_check.notes)


def test_the_active_planner_prompt_is_the_design_system_one() -> None:
    bundle = get_prompt_registry().load("deck_planner")
    assert bundle.version == "1.2.0"
    assert "design_menu" in bundle.system_template


# --- композитор -----------------------------------------------------------------------


ITEMS = [BulletItem(text="Разбор шаблона"), BulletItem(text="Сборка колоды")]
ICON_ITEMS = [
    BulletItem(text="Разбор шаблона", icon="search"),
    BulletItem(text="Сборка колоды", icon="layers"),
]


@pytest.mark.parametrize(
    ("order", "block", "fulfilled"),
    [
        ("callout:insight", CalloutBlock(block_id="c", tone="insight", text="Вывод"), True),
        ("callout:insight", CalloutBlock(block_id="c", tone="risk", text="Риск"), False),
        ("callout:risk", CalloutBlock(block_id="c", tone="risk", text="Риск"), True),
        ("quote", QuoteBlock(block_id="q", text="Слова", author="Автор"), True),
        ("bullets:icon", BulletsBlock(block_id="b", items=ICON_ITEMS, style="icon"), True),
        ("bullets:icon", BulletsBlock(block_id="b", items=ITEMS), False),
        ("bullets:numbered", BulletsBlock(block_id="b", items=ITEMS, style="numbered"), True),
        ("bullets:numbered", BulletsBlock(block_id="b", items=ITEMS, style="bulleted"), False),
        # У схемы вид — подсказка композитору, а не условие: так было до этого change.
        ("smartart:process", SmartArtBlock(block_id="s", pattern="matrix", items=["А", "Б"]), True),
    ],
)
def test_a_design_order_is_fulfilled_only_by_its_own_kind(
    order: str, block: Any, fulfilled: bool
) -> None:
    assert _fulfils(order, block) is fulfilled


async def _compose_ordered(
    order: str,
    blocks: list[dict[str, Any]],
    manifest: TemplateManifest,
    content: ContentPackage,
    variant: VariantProfile,
    design: DesignSystem,
) -> SlideComposer:
    composer = SlideComposer(ComposerLlm([TITLE, *blocks]))
    slide = SlidePlan(
        slide_id="s02",
        intent=SlideIntent.PROBLEM,
        headline="Выручка выросла",
        fact_refs=["f001"],
        suggested_visual=order,
    )
    await composer.compose(slide, content, manifest, variant, seed=7, design_system=design)
    return composer


async def test_a_callout_of_the_other_tone_is_named_as_an_unfulfilled_order(
    manifest: TemplateManifest,
    content: ContentPackage,
    variant_a: VariantProfile,
    design: DesignSystem,
) -> None:
    insight = {
        "block_id": "c",
        "type": "callout",
        "tone": "insight",
        "text": "Выручка выросла на 37,5 % за год",
    }
    wrong = await _compose_ordered("callout:risk", [insight], manifest, content, variant_a, design)
    right = await _compose_ordered(
        "callout:insight", [insight], manifest, content, variant_a, design
    )

    assert any("callout:risk" in note for note in wrong.notes), wrong.notes
    assert not any("план заказал" in note for note in right.notes), right.notes


# --- граф -----------------------------------------------------------------------------


class RecordingInference(FakeInference):
    """Подделка сквозного прогона, которая запоминает промпт планировщика."""

    def __init__(self, manifest: TemplateManifest) -> None:
        super().__init__(manifest)
        self.plan_prompt = ""

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        if kwargs.get("schema_name") == "DeckPlan":
            self.plan_prompt = "\n".join(str(m.get("content", "")) for m in messages)
        return super().complete(messages, **kwargs)


async def test_the_design_system_of_the_parse_node_reaches_the_planner(
    workspace: dict[str, Path],
) -> None:
    """ДС считается один раз в узле `parse` и доходит до плана сама, а не передаётся руками."""
    root = workspace["root"]
    manifest = TemplateParser(cache_dir=root / "cache").parse(workspace["template"])
    llm = RecordingInference(manifest)
    out_dir = root / "artifacts" / "A"
    deps = Deps(
        brief=load_brief(workspace["brief"]),
        run=RunConfig(exports=["pptx"], audit={"run_semantic": False, "auto_fix": False}),
        out_dir=out_dir,
        llm=llm,
        fonts=theme_fonts(root, manifest),
        cache_dir=root / "cache",
        work_dir=out_dir,
    )
    result = await generate_variant(
        workspace["template"],
        collect_content_paths(workspace["content"]),
        load_variant_profiles()["A"],
        deps,
        seed=1337,
        run_id="plan-ds",
    )

    menu = design_menu(result.state["design_system"])
    assert menu, "ДС стандартного шаблона не дала плану ни одного элемента"
    for item in menu:
        assert f"`{item.order}`" in llm.plan_prompt
    assert json.loads(json.dumps(result.report()))["design_system"] is not None
