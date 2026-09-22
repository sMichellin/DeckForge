"""Выбор макета по слайдам-примерам шаблона. Задача DS5.

Вид макета мы угадываем классификатором, а примеры — это то, что автор шаблона положил
на макет сам. Проверяется не «качество выбора», а правила: когда слово автора перевешивает
нашу догадку о виде, когда не перевешивает и что при этом не ломается.
"""

from __future__ import annotations

import pytest

from deckforge.composition.example_fit import (
    layout_schema,
    ranked_by_example,
    schema_distance,
    slide_schema,
)
from deckforge.composition.layout_picker import pick_layout
from deckforge.domain.enums import LayoutKind, SlideIntent, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import (
    ExampleShape,
    LayoutCapacity,
    LayoutSpec,
    PlaceholderSpec,
    ShapeKind,
    TemplateExample,
    TemplateManifest,
)
from deckforge.domain.variants import VariantProfile
from deckforge.registry import load_variant_profiles

EMU_PER_CM = 360_000


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


def plan_slide(
    intent: SlideIntent = SlideIntent.PROBLEM, facts: int = 4, **kwargs: object
) -> SlidePlan:
    return SlidePlan(
        slide_id="s02",
        intent=intent,
        headline="Отток снизился втрое за год",
        fact_refs=[f"f{i:03d}" for i in range(1, facts + 1)],
        **kwargs,  # type: ignore[arg-type]
    )


def text_shape(index: int, role: TextRole | None = None) -> ExampleShape:
    return ExampleShape(
        shape_id=f"sh{index}",
        kind=ShapeKind.TEXT,
        x=EMU_PER_CM,
        y=index * EMU_PER_CM,
        cx=5 * EMU_PER_CM,
        cy=EMU_PER_CM,
        role=role,
        text_len=40,
    )


def picture_shape(index: int) -> ExampleShape:
    return ExampleShape(
        shape_id=f"pic{index}",
        kind=ShapeKind.PICTURE,
        x=EMU_PER_CM,
        y=index * EMU_PER_CM,
        cx=5 * EMU_PER_CM,
        cy=4 * EMU_PER_CM,
    )


def example(
    layout_id: str, *, texts: int = 0, pictures: int = 0, index: int = 1
) -> TemplateExample:
    """Слайд-пример: заголовок плюс столько текстов и картинок, сколько сказано."""
    shapes = [text_shape(0, TextRole.TITLE)]
    shapes += [text_shape(i + 1) for i in range(texts)]
    shapes += [picture_shape(i + 1) for i in range(pictures)]
    return TemplateExample(slide_index=index, layout_id=layout_id, shapes=shapes)


def wide_body(idx: int, manifest: TemplateManifest) -> PlaceholderSpec:
    """Тело во всю область контента: покрытие почти полное."""
    content = manifest.content_bbox
    return PlaceholderSpec(
        idx=idx, ph_type="BODY", role=TextRole.BODY,
        x=content.x, y=content.y + 3 * EMU_PER_CM,
        cx=content.cx, cy=content.cy - 3 * EMU_PER_CM,
    )


def narrow_body(idx: int, manifest: TemplateManifest) -> PlaceholderSpec:
    """Узкая полоса сбоку: вместимость есть, а слайд остаётся пустым наполовину."""
    content = manifest.content_bbox
    return PlaceholderSpec(
        idx=idx, ph_type="BODY", role=TextRole.BODY,
        x=content.x + int(content.cx * 0.6), y=content.y + 3 * EMU_PER_CM,
        cx=int(content.cx * 0.4), cy=content.cy - 3 * EMU_PER_CM,
    )


def with_layouts(
    manifest: TemplateManifest, *layouts: LayoutSpec, examples: list[TemplateExample] | None = None
) -> TemplateManifest:
    return manifest.model_copy(
        update={"layouts": list(layouts), "examples": list(examples or [])}
    )


def layout(
    manifest: TemplateManifest,
    layout_id: str,
    kind: LayoutKind,
    body: PlaceholderSpec | None,
    index: int,
) -> LayoutSpec:
    source = manifest.layouts[1]
    title = source.placeholders[0]
    return source.model_copy(
        update={
            "layout_id": layout_id,
            "name": layout_id,
            "index": index,
            "kind": kind,
            "placeholders": [title, *([body] if body else [])],
            "capacity": LayoutCapacity(
                max_bullets=6, max_chars_body=400 if body else 0, max_chars_title=90
            ),
        }
    )


# --- слово автора шаблона перевешивает наш вид макета --------------------------


def test_examples_beat_our_guess_about_the_kind(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """DS5. На VK Tech цепочка видов приводит слайд к макетам «Содержание» с пустой
    половиной, а макет, где автор разложил четыре текстовых блока, классифицирован
    `custom` и в цепочку не входит вовсе.
    """
    by_kind = layout(manifest, "K01", LayoutKind.BULLETS, narrow_body(1, manifest), 0)
    by_author = layout(manifest, "A01", LayoutKind.CUSTOM, wide_body(1, manifest), 1)
    template = with_layouts(
        manifest,
        by_kind,
        by_author,
        examples=[example("A01", texts=4), example("K01", pictures=9, index=2)],
    )

    assert pick_layout(plan_slide(), template, variant_a).layout_id == "A01"


def test_a_template_without_examples_is_picked_as_before(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: примеров нет — решает цепочка видов и вместимость, как до DS5."""
    by_kind = layout(manifest, "K01", LayoutKind.BULLETS, narrow_body(1, manifest), 0)
    by_author = layout(manifest, "A01", LayoutKind.CUSTOM, wide_body(1, manifest), 1)
    template = with_layouts(manifest, by_kind, by_author)

    assert pick_layout(plan_slide(), template, variant_a).layout_id == "K01"


def test_coverage_decides_between_equally_close_examples(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """У примеров 94 % содержательных фигур лежат вне плейсхолдеров (VK Tech — 6 % внутри).

    Значит «макет, который автор взял под такое содержание» сам по себе не делает слайд
    полным: среди равно близких по схеме выигрывает тот, где содержанию есть место.
    """
    narrow = layout(manifest, "N01", LayoutKind.CUSTOM, narrow_body(1, manifest), 0)
    wide = layout(manifest, "W01", LayoutKind.CUSTOM, wide_body(1, manifest), 1)
    # Схема узкого макета совпадает со слайдом точно, у широкого — расходится на три:
    # выбери мы «по примерам в первую очередь», победил бы узкий, и слайд снова остался
    # бы пустым наполовину. Этот тест сторожит порядок, а не наличие DS5.
    template = with_layouts(
        manifest, narrow, wide,
        examples=[example("N01", texts=4), example("W01", texts=1, index=2)],
    )

    assert pick_layout(plan_slide(), template, variant_a).layout_id == "W01"


def test_a_cover_is_never_given_to_a_content_slide(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Пример на обложке — «заголовок и подпись», и слайд с тезисами подходит к нему
    по схеме лучше всех. Так на VK Education титульный макет доставался всем восьми
    содержательным слайдам разом, а на VK WorkSpace — макет перебивки.

    Тест сторожит отбор внутри DS5: без примеров цепочка видов обложку и так не отдаст.
    """
    cover = layout(manifest, "T01", LayoutKind.TITLE, None, 0)
    content = layout(manifest, "C01", LayoutKind.CUSTOM, wide_body(1, manifest), 1)
    template = with_layouts(
        manifest, cover, content,
        examples=[example("T01", texts=4), example("C01", texts=1, index=2)],
    )

    assert pick_layout(plan_slide(), template, variant_a).layout_id == "C01"


def test_the_title_slide_ignores_examples(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: титулу вид макета задаёт роль, а схема содержания у него пустая."""
    cover = layout(manifest, "T01", LayoutKind.TITLE, None, 0)
    content = layout(manifest, "C01", LayoutKind.CUSTOM, wide_body(1, manifest), 1)
    template = with_layouts(
        manifest, cover, content,
        examples=[example("C01", texts=4), example("T01", texts=1, index=2)],
    )

    assert pick_layout(plan_slide(SlideIntent.TITLE), template, variant_a).kind is LayoutKind.TITLE


# --- мера близости -------------------------------------------------------------


def test_schema_of_a_layout_without_examples_is_unknown(manifest: TemplateManifest) -> None:
    """`None`, а не пустая схема: «автор ничего не клал» и «мы не знаем» — разное."""
    template = with_layouts(manifest, *manifest.layouts, examples=[example("L07", texts=2)])

    assert layout_schema("L07", template) is not None
    assert layout_schema("L01", template) is None


def test_schema_of_several_examples_is_their_median(manifest: TemplateManifest) -> None:
    """Медиана, а не среднее: один пример-исключение не должен описывать макет."""
    template = with_layouts(
        manifest, *manifest.layouts,
        examples=[
            example("L07", texts=1),
            example("L07", texts=2, index=2),
            example("L07", texts=12, index=3),
        ],
    )

    assert layout_schema("L07", template)["text"] == 2


def test_decor_without_text_is_not_counted(manifest: TemplateManifest) -> None:
    """Фигура без текста и без картинки — декор шаблона, его рисует макет."""
    decor = ExampleShape(
        shape_id="d1", kind=ShapeKind.SHAPE,
        x=0, y=0, cx=EMU_PER_CM, cy=EMU_PER_CM, text_len=0,
    )
    plain = example("L07", texts=2)
    decorated = TemplateExample(
        slide_index=2, layout_id="L07", shapes=[*plain.shapes, decor, decor]
    )
    template = with_layouts(manifest, *manifest.layouts, examples=[plain])
    with_decor = with_layouts(manifest, *manifest.layouts, examples=[decorated])

    assert layout_schema("L07", template) == layout_schema("L07", with_decor)


def test_a_long_list_does_not_beat_the_intent_of_the_layout(manifest: TemplateManifest) -> None:
    """Пример с пятнадцатью подписями — это сетка иконок, а не «очень много текста».

    Без предела расстояние мерило бы длину списка, и слайд с пятью тезисами выбирал бы
    макет тем увереннее, чем больше подписей у автора.
    """
    template = with_layouts(
        manifest, *manifest.layouts,
        examples=[example("L07", texts=15), example("L01", texts=8, index=2)],
    )

    assert layout_schema("L07", template)["text"] == layout_schema("L01", template)["text"]


def test_distance_is_zero_when_the_author_laid_out_the_same(manifest: TemplateManifest) -> None:
    template = with_layouts(manifest, *manifest.layouts, examples=[example("L07", texts=4)])
    schema = layout_schema("L07", template)

    assert schema is not None
    assert schema_distance(schema, slide_schema(plan_slide(facts=4))) == 0
    assert schema_distance(schema, slide_schema(plan_slide(facts=1))) == 3


def test_ranking_is_deterministic(manifest: TemplateManifest) -> None:
    """Тот же план — та же колода: при равном расстоянии порядок по `layout_id`."""
    template = with_layouts(
        manifest, *manifest.layouts,
        examples=[example("L07", texts=4), example("L01", texts=4, index=2)],
    )
    order = [layout.layout_id for _, layout in ranked_by_example(plan_slide(), template)]

    assert order == sorted(order)
