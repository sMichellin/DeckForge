"""Свободная зона рядом с местом под тело получает блок. Задача B10.

У макета либо есть место под тело, либо нет. Когда нет, свободная часть слайда и есть
тело (change 25). Когда есть — свободную часть до сих пор не предлагали никому, и на
шаблонах кейса это половина слайда: у VK Tech место под тело обещает промпту 874 знака,
а рядом лежит зона 12,4 × 9,4 см ещё на 954 знака.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deckforge.composition.composer import SlideComposer
from deckforge.composition.free_space import ZONE_MIN_LINES, spare_zone
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import LayoutSpec, PlaceholderSpec, TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import Completion
from deckforge.registry import load_variant_profiles

EMU_PER_CM = 360_000


class FakeLlm:
    model = "fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.prompt = ""

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        self.prompt = "\n".join(str(m.get("content", "")) for m in messages)
        return Completion(text=json.dumps(self.payload, ensure_ascii=False), model=self.model)


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="report", audience="правление", target_slides=6, language="ru"),
        facts=[Fact(fact_id="f001", text="Выручка выросла на 37,5 %")],
    )


def body(manifest: TemplateManifest, *, width_share: float, top_cm: float) -> PlaceholderSpec:
    content_box = manifest.content_bbox
    return PlaceholderSpec(
        idx=1, ph_type="BODY", role=TextRole.BODY,
        x=content_box.x, y=content_box.y + int(top_cm * EMU_PER_CM),
        cx=int(content_box.cx * width_share),
        cy=content_box.cy - int(top_cm * EMU_PER_CM),
    )


def strip(manifest: TemplateManifest) -> PlaceholderSpec:
    """Тело во всю ширину, под ним остаётся полоса в одну строку."""
    content_box = manifest.content_bbox
    return PlaceholderSpec(
        idx=1, ph_type="BODY", role=TextRole.BODY,
        x=content_box.x, y=content_box.y,
        cx=content_box.cx, cy=content_box.cy - EMU_PER_CM,
    )


def template(manifest: TemplateManifest, place: PlaceholderSpec) -> TemplateManifest:
    source = manifest.layouts[1]
    layout = source.model_copy(
        update={"placeholders": [source.placeholders[0], place]}
    )
    return manifest.model_copy(update={"layouts": [layout]})


def only_layout(template_: TemplateManifest) -> LayoutSpec:
    return template_.layouts[0]


# --- когда зона предлагается ---------------------------------------------------


def test_a_wide_and_tall_zone_beside_a_narrow_body_is_offered(
    manifest: TemplateManifest,
) -> None:
    """Тело на 40 % ширины — рядом остаётся половина слайда, и она ничья."""
    narrow = template(manifest, body(manifest, width_share=0.4, top_cm=3))
    zone = spare_zone(only_layout(narrow), narrow)

    assert zone is not None
    assert zone.max_bullets >= ZONE_MIN_LINES


def test_a_one_line_strip_is_not_offered(manifest: TemplateManifest) -> None:
    """A13, прогон add3de1e5918: свободный блок получил 30 × 1,5 см и выродился в список.

    Полоса в одну строку — не место под блок: предложить её значит разменять пустоту
    на переполнение.
    """
    thin = template(manifest, strip(manifest))

    assert spare_zone(only_layout(thin), thin) is None


def test_a_full_width_body_leaves_no_zone(manifest: TemplateManifest) -> None:
    """Норма: тело занимает область контента — предлагать нечего."""
    full = template(manifest, body(manifest, width_share=1.0, top_cm=3))

    assert spare_zone(only_layout(full), full) is None


def test_a_layout_without_a_body_slot_has_no_spare_zone(manifest: TemplateManifest) -> None:
    """Норма: там свободная часть и есть тело (change 25), а не добавка к нему."""
    title_only = manifest.model_copy(update={"layouts": [manifest.layouts[0]]})

    assert spare_zone(title_only.layouts[0], title_only) is None


# --- что видит модель и что происходит с её ответом -----------------------------


async def test_the_prompt_names_the_zone(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """До B10 о зоне не говорилось никому, и модель заполняла только тело."""
    narrow = template(manifest, body(manifest, width_share=0.4, top_cm=3))
    payload = {
        "slide_id": "s02", "layout_id": narrow.layouts[0].layout_id, "variant": "A",
        "blocks": [
            {"block_id": "t", "type": "text", "placeholder_idx": 0,
             "role": "title", "text": "Отток снизился втрое"},
        ],
    }
    llm = FakeLlm(payload)
    await SlideComposer(llm).compose(
        SlidePlan(slide_id="s02", intent=SlideIntent.PROBLEM,
                  headline="Отток снизился втрое", fact_refs=["f001"]),
        content, narrow, variant_a, seed=1,
    )

    assert "свободная зона" in llm.prompt


async def test_the_second_block_lands_in_the_zone_and_not_on_the_body(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Блок без плейсхолдера обязан встать рядом с телом, а не поверх него."""
    narrow = template(manifest, body(manifest, width_share=0.4, top_cm=3))
    layout = narrow.layouts[0]
    payload = {
        "slide_id": "s02", "layout_id": layout.layout_id, "variant": "A",
        "blocks": [
            {"block_id": "t", "type": "text", "placeholder_idx": 0,
             "role": "title", "text": "Отток снизился втрое"},
            {"block_id": "b", "type": "text", "placeholder_idx": 1,
             "role": "body", "text": "Первый довод по материалам"},
            {"block_id": "z", "type": "bullets",
             "items": [{"text": "Первое"}, {"text": "Второе"}, {"text": "Третье"}]},
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        SlidePlan(slide_id="s02", intent=SlideIntent.PROBLEM,
                  headline="Отток снизился втрое", fact_refs=["f001"]),
        content, narrow, variant_a, seed=1,
    )

    zone_block = ir.block("z")
    assert zone_block is not None and zone_block.bbox is not None
    assert narrow.content_bbox.contains(zone_block.bbox)
    body_box = layout.placeholder(1).bbox
    assert zone_block.bbox.intersection_area(body_box) == 0, "блок лёг поверх тела"
