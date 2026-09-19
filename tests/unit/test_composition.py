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
from deckforge.composition.layout_picker import (
    INTENT_LAYOUTS,
    MAX_CONTENT_LAYOUTS,
    content_palette,
    kind_chain,
    pick_layout,
)
from deckforge.composition.visual_selector import looks_like_time_series, select_chart
from deckforge.domain.content import Brief, ContentPackage, Dataset, Fact, Series
from deckforge.domain.enums import ChartType, LayoutKind, SlideIntent, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import LayoutBackground, TemplateManifest
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


async def test_text_with_a_foreign_placeholder_is_kept_not_dropped(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Раньше такой блок выбрасывался — это и был дефект интеграционного прогона.

    Плейсхолдера с таким номером в макете нет, но текст от этого не перестаёт быть
    содержанием слайда: он встаёт свободным блоком в область контента.
    """
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
    composer = SlideComposer(FakeLlm(payload))
    ir = await composer.compose(plan_slide(), content, manifest, variant_a, seed=1)

    assert [block.block_id for block in ir.blocks] == ["b1", "b2"]
    body = ir.block("b2")
    assert body is not None and body.placeholder_idx is None and body.bbox is not None
    assert any("b2" in note for note in composer.notes)


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
            # Диаграмма на несуществующих данных: свободным блоком её не поставишь,
            # рисовать нечего — и от слайда не остаётся ничего.
            {"block_id": "b9", "type": "chart", "chart_type": "clustered_column",
             "dataset_ref": "d999"}
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


# ------------------------------------- дефекты интеграционного прогона через UI


def _title_only_manifest(manifest: TemplateManifest) -> TemplateManifest:
    """Шаблон, где под текст нет ни одного плейсхолдера, кроме заголовка.

    Так устроен VK WorkSpace: макетов под содержание в нём нет вовсе, и основной
    текст слайда исчезал молча.
    """
    bullets = manifest.layouts[1]
    title_ph = [ph for ph in bullets.placeholders if ph.role == TextRole.TITLE]
    crippled = bullets.model_copy(update={"placeholders": title_ph})
    return manifest.model_copy(update={"layouts": [manifest.layouts[0], crippled]})


async def test_text_without_a_placeholder_becomes_a_free_block(
    content: ContentPackage, variant_a: VariantProfile, manifest: TemplateManifest
) -> None:
    """Дефект: основной текст выбрасывался без следа. Теперь он встаёт свободным блоком."""
    crippled = _title_only_manifest(manifest)
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title",
             "text": "Отток снизился втрое за год"},
            {"block_id": "b2", "type": "bullets", "placeholder_idx": 1,
             "items": [{"text": "Выручка выросла"}, {"text": "Отток снизился"}]},
        ],
    }
    composer = SlideComposer(FakeLlm(payload))
    ir = await composer.compose(plan_slide(), content, crippled, variant_a, seed=1)

    body = ir.block("b2")
    assert body is not None, "основной текст пропал со слайда"
    assert body.placeholder_idx is None
    assert body.bbox is not None, "свободному блоку нужны координаты, иначе рендерер откажет"
    assert crippled.content_bbox.contains(body.bbox), "блок вышел за поля шаблона"
    assert any("свободным блоком" in note for note in composer.notes)


async def test_every_change_and_loss_is_reported(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Молчаливая потеря — худший исход: на слайде нет половины содержания, и непонятно почему."""
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"},
            {"block_id": "b9", "type": "chart", "chart_type": "clustered_column",
             "dataset_ref": "d999"},
        ],
    }
    composer = SlideComposer(FakeLlm(payload))
    ir = await composer.compose(plan_slide(), content, manifest, variant_a, seed=1)

    assert ir.block("b9") is None, "диаграмма на несуществующих данных осталась"
    assert any("b9" in note and "d999" in note for note in composer.notes)
    assert all(note.startswith("слайд s02:") for note in composer.notes)


async def test_text_in_a_placeholder_gets_no_colour(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Дефект: заголовки выходили dk1 поверх тёмного фона. Цвет знает макет, не модель."""
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "b1", "type": "text", "placeholder_idx": 0, "role": "title",
             "text": "Заголовок", "color_ref": "dk1"},
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        plan_slide(), content, manifest, variant_a, seed=1
    )
    title = ir.block("b1")
    assert title is not None
    assert title.color_ref is None, "цвет в плейсхолдере перебивает цвет макета"


async def test_prompt_forbids_colouring_text_in_placeholders(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
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
    assert "цвет не задавай вовсе" in llm.prompt


# ------------------------------------------- основной текст свободным блоком (#62)


def title_only_template(manifest: TemplateManifest, count: int = 6) -> TemplateManifest:
    """Шаблон, где **ни один** макет не размечен под основной текст.

    Так устроен VK WorkSpace: во всех пятнадцати макетах один плейсхолдер — заголовок.
    Фоны нарочно повторяются: палитра обязана выбирать непохожие.
    """
    source = next(item for item in manifest.layouts if item.kind is LayoutKind.TITLE)
    backgrounds = ["#101014", "#101014", "#0C2D59", "#101014", "#01111C", "#101014"]
    return manifest.model_copy(
        update={
            "layouts": [
                source.model_copy(
                    update={
                        "layout_id": f"T{index:02d}",
                        "name": f"Макет {index}",
                        "index": index,
                        "kind": LayoutKind.SECTION if index == 1 else LayoutKind.TITLE,
                        "background": LayoutBackground(
                            color_hex=backgrounds[index % len(backgrounds)], source="layout"
                        ),
                    }
                )
                for index in range(count)
            ]
        }
    )


def test_content_slides_do_not_all_land_on_one_layout(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Дефект прогонов b8549ea89984 и 4197f2e8331f: двенадцать слайдов на одной подложке.

    Все макеты шаблона равно непригодны под текст, `max(..., key=max_chars_body)`
    отдавал первый, и колода выходила из двенадцати одинаковых слайдов.
    """
    template = title_only_template(manifest)
    chosen = [
        pick_layout(plan_slide(SlideIntent.PROBLEM, slide_id=f"s{n:02d}"), template, variant_a)
        for n in range(2, 12)
    ]
    assert len({layout.layout_id for layout in chosen}) > 1


def test_content_slides_keep_to_a_couple_of_layouts(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Разнообразие ограничено: презентация держится на повторе, а не на переборе."""
    template = title_only_template(manifest)
    chosen = {
        pick_layout(
            plan_slide(SlideIntent.PROBLEM, slide_id=f"s{n:02d}"), template, variant_a
        ).layout_id
        for n in range(2, 14)
    }
    assert len(chosen) <= MAX_CONTENT_LAYOUTS


def test_content_slides_do_not_reuse_the_title_layout(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Титул посреди колоды читается как начало новой презентации."""
    template = title_only_template(manifest)
    title = pick_layout(plan_slide(SlideIntent.TITLE, slide_id="s01"), template, variant_a)
    content_layouts = {
        pick_layout(
            plan_slide(SlideIntent.PROBLEM, slide_id=f"s{n:02d}"), template, variant_a
        ).layout_id
        for n in range(2, 12)
    }
    assert title.layout_id not in content_layouts


def test_content_palette_prefers_different_backgrounds(manifest: TemplateManifest) -> None:
    """Жалоба по прогону: «подложки везде одинаковые». Фон и есть то, что видно."""
    template = title_only_template(manifest)
    palette = content_palette(template, list(template.layouts))
    backgrounds = {layout.background.color_hex for layout in palette if layout.background}
    assert len(backgrounds) == len(palette)


def test_layout_choice_is_deterministic(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Тот же план — та же колода: иначе два прогона не сравнить ни глазом, ни тестом."""
    template = title_only_template(manifest)
    slide = plan_slide(SlideIntent.PROBLEM, slide_id="s05")
    first = pick_layout(slide, template, variant_a)
    assert all(
        pick_layout(slide, template, variant_a).layout_id == first.layout_id for _ in range(5)
    )


def test_capacious_layout_still_wins_when_capacity_differs(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма к той же правке: где вместимость различает макеты, она и решает."""
    layout = pick_layout(plan_slide(SlideIntent.PROBLEM), manifest, variant_a)
    assert layout.layout_id == "L07"
    assert layout.capacity.max_chars_body == 420


async def test_body_without_placeholder_or_coordinates_gets_a_place(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Главное по #62: модель отдаёт основной текст свободным блоком, и он не теряется."""
    template = title_only_template(manifest)
    payload = {
        "slide_id": "s02",
        "layout_id": "T00",
        "variant": "A",
        "blocks": [
            {
                "block_id": "t",
                "type": "text",
                "placeholder_idx": 0,
                "role": "title",
                "text": "Отток снизился втрое",
            },
            {
                "block_id": "b",
                "type": "bullets",
                "items": [{"text": "Первый довод"}, {"text": "Второй довод"}],
            },
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        plan_slide(), content, template, variant_a, seed=1
    )
    body = ir.block("b")
    assert body is not None, "основной текст потерян — это и был дефект"
    assert body.bbox is not None, "свободному блоку не дали места"
    assert template.content_bbox.contains(body.bbox)


async def test_free_body_does_not_land_on_the_title(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Заголовок VK WorkSpace шире полей шаблона: проверка «целиком внутри» его не видела."""
    template = title_only_template(manifest)
    layout = template.layout("T00")
    assert layout is not None
    wide = layout.placeholders[0].model_copy(
        update={"x": 0, "cx": template.slide_size.cx_emu}
    )
    template = template.model_copy(
        update={
            "layouts": [
                item.model_copy(update={"placeholders": [wide]})
                if item.layout_id == "T00"
                else item
                for item in template.layouts
            ]
        }
    )
    payload = {
        "slide_id": "s02",
        "layout_id": "T00",
        "variant": "A",
        "blocks": [
            {"block_id": "t", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"},
            {"block_id": "b", "type": "text", "role": "body", "text": "Основной текст"},
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        plan_slide(), content, template, variant_a, seed=1
    )
    body = ir.block("b")
    assert body is not None and body.bbox is not None
    assert body.bbox.intersection_area(wide.bbox) == 0, "текст лёг поверх заголовка"


async def test_smartart_without_a_place_is_kept_not_dropped(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Инфографика из фигур PowerPoint — содержание слайда, а не оформление."""
    template = title_only_template(manifest)
    payload = {
        "slide_id": "s02",
        "layout_id": "T00",
        "variant": "A",
        "blocks": [
            {"block_id": "t", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"},
            {
                "block_id": "d",
                "type": "smartart",
                "pattern": "process",
                "items": ["Сбор", "Разбор", "Сборка"],
            },
        ],
    }
    ir = await SlideComposer(FakeLlm(payload)).compose(
        plan_slide(), content, template, variant_a, seed=1
    )
    diagram = ir.block("d")
    assert diagram is not None and diagram.bbox is not None


async def test_block_that_cannot_be_placed_freely_is_reported(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Диаграмме нужен не прямоугольник, а макет, который её допускает. Потеря — в отчёт."""
    template = title_only_template(manifest)
    payload = {
        "slide_id": "s02",
        "layout_id": "T00",
        "variant": "A",
        "blocks": [
            {"block_id": "t", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"},
            {
                "block_id": "c",
                "type": "chart",
                "chart_type": "clustered_column",
                "dataset_ref": "d001",
            },
        ],
    }
    composer = SlideComposer(FakeLlm(payload))
    ir = await composer.compose(plan_slide(), content, template, variant_a, seed=1)
    assert ir.block("c") is None
    assert any("c" in note and "координат" in note for note in composer.notes)


async def test_prompt_asks_for_a_free_block_when_there_is_no_body_slot(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Промпт запрещал чужие idx и показывал вместимость 0 — модель отдавала заголовок."""
    template = title_only_template(manifest)
    payload = {
        "slide_id": "s02",
        "layout_id": "T00",
        "variant": "A",
        "blocks": [
            {"block_id": "t", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"}
        ],
    }
    llm = FakeLlm(payload)
    await SlideComposer(llm).compose(plan_slide(), content, template, variant_a, seed=1)
    assert "свободным блоком" in llm.prompt
    assert "не более 0 знаков" not in llm.prompt
    assert "smartart" in llm.prompt


async def test_prompt_says_nothing_about_free_blocks_when_the_layout_has_a_body(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: макет предусмотрел место под текст — просить свободный блок незачем."""
    payload = {
        "slide_id": "s02",
        "layout_id": "L07",
        "variant": "A",
        "blocks": [
            {"block_id": "t", "type": "text", "placeholder_idx": 0, "role": "title", "text": "З"}
        ],
    }
    llm = FakeLlm(payload)
    await SlideComposer(llm).compose(plan_slide(), content, manifest, variant_a, seed=1)
    assert "Плейсхолдера под основной текст в этом макете нет" not in llm.prompt
