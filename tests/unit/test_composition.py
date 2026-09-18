"""Композиция слайда. Change (11) `slide-composition`.

Проверяется не красота вёрстки, а инварианты: макет всегда из манифеста и никогда
по имени, предпочтение варианта работает как приоритет, а не фильтр, висячие ссылки
не доезжают до рендерера.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deckforge.composition.composer import MAX_BULLETS_BY_SPEC, CompositionError, SlideComposer
from deckforge.composition.layout_picker import INTENT_LAYOUTS, kind_chain, pick_layout
from deckforge.composition.visual_selector import looks_like_time_series, select_chart
from deckforge.domain.content import Brief, ContentPackage, Dataset, Fact, Series
from deckforge.domain.enums import ChartType, LayoutKind, SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import Completion
from deckforge.registry import load_variant_profiles


class FakeLlm:
    model = "fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        self.prompt = "\n".join(str(m.get("content", "")) for m in messages)
        return Completion(text=json.dumps(self.payload, ensure_ascii=False), model=self.model)


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.fixture
def variant_b() -> VariantProfile:
    return load_variant_profiles()["B"]


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[Fact(fact_id="f001", text="Выручка выросла на 37,5 %")],
        datasets=[
            Dataset(
                dataset_id="d001",
                title="Выручка по кварталам, млн ₽",
                categories=["Q1", "Q2", "Q3", "Q4"],
                series=[Series(name="2026", values=[241.0, 287.0, 312.0, 360.0])],
                unit="млн ₽",
            )
        ],
    )


def plan_slide(intent: SlideIntent = SlideIntent.PROBLEM, **kwargs: Any) -> SlidePlan:
    data = {
        "slide_id": "s02",
        "intent": intent,
        "headline": "Отток снизился втрое за год",
        "fact_refs": ["f001"],
        **kwargs,
    }
    return SlidePlan(**data)


# ------------------------------------------------------------------ подбор макета


def test_layout_always_comes_from_the_manifest(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    layout = pick_layout(plan_slide(), manifest, variant_a)
    assert layout.layout_id in {item.layout_id for item in manifest.layouts}


def test_title_slide_ignores_the_variant_preference(
    manifest: TemplateManifest, variant_b: VariantProfile
) -> None:
    """Титул обязан быть титулом в любом варианте вёрстки."""
    layout = pick_layout(plan_slide(SlideIntent.TITLE), manifest, variant_b)
    assert layout.kind == LayoutKind.TITLE


def test_missing_kind_degrades_inside_the_same_template(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """В синтетическом шаблоне есть только title и bullets: chart для evidence не найдётся."""
    layout = pick_layout(plan_slide(SlideIntent.EVIDENCE, dataset_ref="d001"), manifest, variant_a)
    assert layout.kind == LayoutKind.BULLETS
    assert layout.layout_id in {item.layout_id for item in manifest.layouts}


def test_variant_preference_is_a_priority_not_a_filter(variant_b: VariantProfile) -> None:
    """Иначе на шаблоне без kpi и image_full вариант B остался бы без макетов вовсе."""
    chain = kind_chain(plan_slide(SlideIntent.METRICS, dataset_ref="d001"), variant_b)
    assert chain[0] in variant_b.layout_preference
    assert set(INTENT_LAYOUTS[SlideIntent.METRICS]).issubset(set(chain))


def test_variant_may_not_add_a_kind_the_slide_cannot_fill(variant_b: VariantProfile) -> None:
    """image_full у слайда без картинки дал бы пустую рамку во весь экран."""
    chain = kind_chain(plan_slide(SlideIntent.PROBLEM), variant_b)
    assert LayoutKind.IMAGE_FULL not in chain


# ------------------------------------------------------------- выбор диаграммы


def test_quarters_are_recognised_as_a_time_series() -> None:
    assert looks_like_time_series(["Q1", "Q2", "Q3", "Q4"])
    assert looks_like_time_series(["2024", "2025", "2026"])
    assert looks_like_time_series(["январь", "февраль", "март", "Итого"]), "одна лишняя подпись"
    assert not looks_like_time_series(["Крупный бизнес", "Средний бизнес", "Малый бизнес"])


def test_chart_type_is_deterministic(content: ContentPackage) -> None:
    dataset = content.datasets[0]
    assert select_chart(dataset) == select_chart(dataset)
    assert select_chart(dataset) in set(ChartType)


# ------------------------------------------------------------------- композиция


async def test_layout_and_variant_are_forced_by_the_pipeline(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Модель может назвать любой layout_id — на слайд попадёт выбранный правилом."""
    payload = {
        "slide_id": "s99",
        "layout_id": "ВЫДУМАННЫЙ",
        "variant": "Z",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title",
             "text": "Отток снизился втрое за год"}
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        plan_slide(), content, manifest, variant_a, seed=7
    )

    assert ir.layout_id in {item.layout_id for item in manifest.layouts}
    assert ir.slide_id == "s02"
    assert ir.variant == "A"
    assert ir.provenance.seed == 7
    assert ir.provenance.prompt_version == "slide_composer@1.0.0"


async def test_blocks_pointing_at_foreign_placeholders_are_dropped(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title",
             "text": "Заголовок"},
            {"block_id": "b2", "type": "text", "placeholder_idx": 42, "role": "body",
             "text": "Плейсхолдера 42 в макете нет"},
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        plan_slide(), content, manifest, variant_a, seed=1
    )
    assert [block.block_id for block in ir.blocks] == ["b1"]


async def test_bullets_are_capped_by_the_spec(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {
                "block_id": "b1",
                "type": "bullets",
                "placeholder_idx": 1,
                "items": [{"text": f"тезис {i}"} for i in range(1, 12)],
            }
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        plan_slide(), content, manifest, variant_a, seed=1
    )
    bullets = ir.blocks[0]
    assert len(bullets.items) <= MAX_BULLETS_BY_SPEC  # type: ignore[union-attr]


async def test_slide_without_usable_blocks_is_refused(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Пустой слайд в колоде — нарушение целостности из Приложения 1 ТЗ."""
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 77, "role": "body", "text": "x"}
        ],
    }
    with pytest.raises(CompositionError):
        await SlideComposer(FakeLlm(payload)).compose(
            plan_slide(), content, manifest, variant_a, seed=1
        )


async def test_prompt_tells_the_model_which_lever_to_pull(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """По умолчанию сокращается текст; при просьбе сохранить формулировки — визуализация."""
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"}
        ],
    }
    llm = FakeLlm(payload)
    await SlideComposer(llm).compose(plan_slide(), content, manifest, variant_a, seed=1)
    assert "сокращай текст" in llm.prompt

    llm2 = FakeLlm(payload)
    await SlideComposer(llm2).compose(
        plan_slide(), content, manifest, variant_a, seed=1, preserve_wording=True
    )
    assert "не сокращай" in llm2.prompt


# ------------------------------------------------- три варианта вёрстки (change 20)


def _rich_manifest(manifest: TemplateManifest) -> TemplateManifest:
    """Шаблон с богатым набором видов: на бедном варианты различаться не обязаны.

    Синтетический манифест из conftest знает только title и bullets — на нём все три
    варианта честно сойдутся к одному макету, и проверка различимости ничего не скажет.
    """
    base = manifest.layouts[1]
    extra = [
        base.model_copy(update={"layout_id": f"L{20 + i}", "name": f"Макет {kind.value}",
                                "index": 10 + i, "kind": kind})
        for i, kind in enumerate(
            [LayoutKind.KPI, LayoutKind.CHART, LayoutKind.TABLE, LayoutKind.TWO_COLUMN]
        )
    ]
    return manifest.model_copy(update={"layouts": [*manifest.layouts, *extra]})


def test_three_variants_lay_the_same_slide_out_differently(
    manifest: TemplateManifest,
) -> None:
    """C7: варианты обязаны быть визуально различимы, а не только называться по-разному."""
    rich = _rich_manifest(manifest)
    slide = plan_slide(SlideIntent.METRICS, dataset_ref="d001")
    profiles = load_variant_profiles()

    chosen = {
        variant_id: pick_layout(slide, rich, profile).kind
        for variant_id, profile in profiles.items()
    }
    assert len(set(chosen.values())) > 1, f"все варианты выбрали одно и то же: {chosen}"


def test_variants_differ_in_target_density() -> None:
    """Вторая объявленная ось: плотность. Она задаёт, сколько текста просить у модели."""
    ratios = {vid: profile.capacity_ratio() for vid, profile in load_variant_profiles().items()}
    assert len(set(ratios.values())) == len(ratios), f"плотности совпали: {ratios}"


def test_dense_variant_stays_within_the_spec_fill_limit() -> None:
    """Приложение 1 ТЗ считает нарушением заполненность выше трёх четвертей.

    `capacity_ratio` — доля вместимости плейсхолдера, а не площади слайда, поэтому
    прямого конфликта нет. Тест фиксирует границу: если кто-то однажды начнёт считать
    им заполненность слайда, о расхождении узнают здесь, а не на защите.
    """
    high = load_variant_profiles()["A"]
    assert high.capacity_ratio() > 0.75, (
        "плотный вариант укладывается в предел ТЗ по площади только потому, "
        "что это разные величины — расхождение должно оставаться осознанным"
    )


async def test_prompt_says_what_is_not_the_models_job(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Схема ответа этого больше не просит (#32) — промпт обязан сказать то же словами.

    Без такой формулировки модель продолжает присылать координаты, подписи осей и
    provenance: схема их не требует, но и не запрещает, а композитор всё равно выбросит.
    """
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"}
        ],
    }
    llm = FakeLlm(payload)
    await SlideComposer(llm).compose(plan_slide(), content, manifest, variant_a, seed=1)

    assert "Координаты не задавай" in llm.prompt
    assert "Подписи осей" in llm.prompt
    assert "provenance" in llm.prompt.lower()
