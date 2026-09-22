"""Шов `derive(manifest) -> DesignSystem`, измеряемая часть. Таск 02 change `design-system-page`.

Ожидаемые доли посчитаны руками по геометрии слайда-примера: фигура в половину ширины
и половину высоты — это четверть площади, и никакой другой ответ здесь не верен.
Коэффициенты контраста — опубликованные величины WCAG, а не пересчёт тем же кодом.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import (
    ColorRoleKind,
    ContrastLevel,
    ContrastPair,
)
from deckforge.domain.enums import ColorRef
from deckforge.domain.template import (
    ExampleShape,
    LayoutBackground,
    ShapeKind,
    TemplateExample,
    TemplateManifest,
)
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template

CASE_TEMPLATES = [
    "VK Tech шаблон.pptx",
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
    "Шаблон презентации VK Education.pptx",
]

GRAY = "#8F8F8F"
DIM_GRAY = "#949494"


def _on_light_background(manifest: TemplateManifest) -> TemplateManifest:
    """Макет L07 получает светлый фон слотом темы: по нему и читается всё остальное."""
    layouts = list(manifest.layouts)
    layouts[1] = layouts[1].model_copy(
        update={
            "background": LayoutBackground(
                color_hex=manifest.theme.colors.lt1, color_ref=ColorRef.LT1, source="layout"
            )
        }
    )
    return manifest.model_copy(update={"layouts": layouts})


def _shape(
    shape_id: str,
    manifest: TemplateManifest,
    *,
    width: float,
    height: float,
    kind: ShapeKind = ShapeKind.SHAPE,
    **colors: object,
) -> ExampleShape:
    """Фигура в долях слайда: доля площади получается перемножением долей сторон."""
    return ExampleShape(
        shape_id=shape_id,
        kind=kind,
        x=0,
        y=0,
        cx=int(manifest.slide_size.cx_emu * width),
        cy=int(manifest.slide_size.cy_emu * height),
        **colors,  # type: ignore[arg-type]
    )


def _with_one_example(manifest: TemplateManifest) -> TemplateManifest:
    """Один слайд-пример на светлом макете: четверть под бледной плашкой, восьмая — под
    акцентом, шестнадцатая — под серой подписью. Остальное — фон макета."""
    manifest = _on_light_background(manifest)
    shapes = [
        _shape("tile", manifest, width=0.5, height=0.5, fill_ref=ColorRef.LT2),
        _shape("badge", manifest, width=0.5, height=0.25, fill_ref=ColorRef.ACCENT1),
        _shape(
            "caption",
            manifest,
            width=0.25,
            height=0.25,
            kind=ShapeKind.TEXT,
            color_hex=GRAY,
            text_len=20,
            size_pt=12.0,
        ),
    ]
    example = TemplateExample(slide_index=1, layout_id="L07", shapes=shapes)
    return manifest.model_copy(update={"examples": [example]})


def _shares(manifest: TemplateManifest) -> dict[str, float]:
    return {role.color_hex: role.share for role in derive(manifest).palette_roles}


def test_the_share_of_a_colour_is_the_area_it_covers_on_the_examples(
    manifest: TemplateManifest,
) -> None:
    """Плашка в пол-слайда по обеим сторонам — четверть площади; непокрытое — фон макета."""
    colors = manifest.theme.colors

    shares = _shares(_with_one_example(manifest))

    assert shares[colors.lt2] == 0.25
    assert shares[colors.accent1] == 0.125
    assert shares[GRAY] == 0.0625
    assert shares[colors.lt1] == 0.5625, "непокрытая фигурами площадь отошла фону макета"


def test_the_roles_follow_the_shares_and_the_grey_stays_out_of_the_accents(
    manifest: TemplateManifest,
) -> None:
    """Серый занимает больше места, чем акцент, и всё равно акцентом не становится:
    роль цвета решает не только доля, но и разброс каналов."""
    colors = manifest.theme.colors

    roles = {
        role.color_hex: role.role
        for role in derive(_with_one_example(manifest)).palette_roles
    }

    assert roles[colors.lt1] is ColorRoleKind.BACKGROUND
    assert roles[colors.lt2] is ColorRoleKind.DOMINANT
    assert roles[colors.accent1] is ColorRoleKind.ACCENT
    assert roles[GRAY] is ColorRoleKind.RARE


def test_the_tail_of_the_palette_is_collapsed_into_one_entry(
    manifest: TemplateManifest,
) -> None:
    """Двенадцать бледных плашек по одному проценту — это не двенадцать строк раздела,
    а строка «ещё N оттенков» с их суммарной долей."""
    manifest = _on_light_background(manifest)
    tiles = [
        _shape(f"t{index}", manifest, width=0.1, height=0.1, fill_hex=f"#{index:02X}{index:02X}30")
        for index in range(1, 13)
    ]
    example = TemplateExample(slide_index=1, layout_id="L07", shapes=tiles)
    ds = derive(manifest.model_copy(update={"examples": [example]}))

    tail = [role for role in ds.palette_roles if role.role is ColorRoleKind.TAIL]
    assert len(tail) == 1, "хвост сворачивается ровно в одну запись"
    assert tail[0].count >= 2
    assert tail[0].label, "запись хвоста без подписи немая"
    assert len(ds.palette_roles) <= 10, "отдельных цветов не больше десяти"
    assert round(sum(role.share for role in ds.palette_roles), 3) == 1.0


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_shares_of_a_case_template_add_up_to_a_hundred_percent(name: str) -> None:
    """Проверка на настоящих шаблонах: доли нормированы, роли названы, акцент найден."""
    parsed = TemplateParser().parse(case_template(name))

    roles = derive(parsed).palette_roles

    assert round(sum(role.share for role in roles) * 100, 1) == pytest.approx(100.0, abs=0.5)
    assert roles[0].role is ColorRoleKind.BACKGROUND
    assert roles[1].role is ColorRoleKind.DOMINANT
    assert any(role.role is ColorRoleKind.ACCENT for role in roles), "акцент шаблона не найден"
    assert len(roles) <= 10, "раздел превращается в простыню"
    assert all(role.seen_on or role.role is ColorRoleKind.TAIL for role in roles)


def test_a_combination_is_the_triple_that_really_stood_on_the_slide(
    manifest: TemplateManifest,
) -> None:
    """Фон макета, самый крупный цвет текста и самая заметная заливка, отличная от фона.
    Бледная плашка занимает больше места, но заметен на слайде насыщенный акцент."""
    colors = manifest.theme.colors

    combinations = derive(_with_one_example(manifest)).combinations

    assert len(combinations) == 1
    assert combinations[0].background_hex == colors.lt1
    assert combinations[0].text_hex == GRAY
    assert combinations[0].accent_hex == colors.accent1
    assert combinations[0].share == 1.0
    assert combinations[0].seen_on == [1]


def test_equal_triples_add_up_and_remember_the_slides(manifest: TemplateManifest) -> None:
    """Сочетание, встреченное на двух слайдах из трёх, — это две трети применения."""
    base = _with_one_example(manifest)
    repeated = base.examples[0]
    other = TemplateExample(
        slide_index=3,
        layout_id="L07",
        shapes=[_shape("tile", base, width=0.5, height=0.5, fill_ref=ColorRef.ACCENT2)],
    )
    ds = derive(
        base.model_copy(
            update={"examples": [repeated, repeated.model_copy(update={"slide_index": 2}), other]}
        )
    )

    assert [combination.share for combination in ds.combinations] == [0.666667, 0.333333]
    assert ds.combinations[0].seen_on == [1, 2]
    assert ds.combinations[1].accent_hex == manifest.theme.colors.accent2
    assert ds.combinations[1].text_hex is None, "текста на слайде не было — и придумывать нечего"


def _pairs_by_colors(manifest: TemplateManifest) -> dict[tuple[str, str], ContrastPair]:
    return {
        (pair.foreground_hex, pair.background_hex): pair
        for pair in derive(manifest).contrast_pairs
    }


def test_the_pair_of_the_scheme_carries_the_ratio_of_wcag(manifest: TemplateManifest) -> None:
    """Тёмный слот темы на светлом: 18,98 — опубликованная величина WCAG для этой пары."""
    colors = manifest.theme.colors

    pair = _pairs_by_colors(_with_one_example(manifest))[(colors.dk1, colors.lt1)]

    assert pair.ratio == 18.98
    assert pair.level is ContrastLevel.AA
    assert pair.from_theme is True
    assert pair.is_risk is False


def test_a_pair_of_the_theme_that_fails_aa_is_marked_as_a_risk(
    manifest: TemplateManifest,
) -> None:
    """Шаблон сам себе противоречит: серый слот темы на её же светлом слоте не читается.
    Такая пара помечается, а не прячется."""
    colors = manifest.theme.colors.model_copy(update={"dk2": DIM_GRAY})
    themed = manifest.model_copy(
        update={"theme": manifest.theme.model_copy(update={"colors": colors})}
    )

    pair = _pairs_by_colors(_with_one_example(themed))[(DIM_GRAY, colors.lt2)]

    assert pair.level is not ContrastLevel.AA
    assert pair.is_risk is True
    assert pair.foreground_label and pair.background_label


def test_an_accent_that_fails_aa_is_good_for_graphics_only(manifest: TemplateManifest) -> None:
    """Акцент, не прошедший AA на светлом фоне шаблона, в абзац не годится — и это сказано
    отдельной отметкой, а не отсутствием пары."""
    colors = manifest.theme.colors.model_copy(update={"accent1": DIM_GRAY, "accent2": "#000000"})
    themed = manifest.model_copy(
        update={"theme": manifest.theme.model_copy(update={"colors": colors})}
    )

    pairs = _pairs_by_colors(_with_one_example(themed))

    assert pairs[(DIM_GRAY, colors.lt1)].display_only is True
    assert pairs[("#000000", colors.lt1)].display_only is False


def test_the_measured_combinations_give_pairs_of_their_own(manifest: TemplateManifest) -> None:
    """Пары берутся не только из темы: то, что встречено на примерах, проверяется тоже."""
    colors = manifest.theme.colors

    pair = _pairs_by_colors(_with_one_example(manifest))[(GRAY, colors.lt1)]

    assert pair.from_theme is False
    assert pair.level is ContrastLevel.AA_LARGE
    assert pair.is_risk is False, "своих цветов шаблон не обещал — это не противоречие темы"
