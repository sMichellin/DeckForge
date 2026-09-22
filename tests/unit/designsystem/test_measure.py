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
    Origin,
)
from deckforge.domain.enums import ColorRef
from deckforge.domain.rules import TEXT_SLOTS
from deckforge.domain.template import (
    ComponentKind,
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
        role.color_hex: role.role for role in derive(_with_one_example(manifest)).palette_roles
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
    #: Утверждение о самом шаблоне, а не о порядке списка: фоном по площади оказался
    #: один из фоновых слотов темы. Порядок этого не обещает — площадь могла достаться
    #: любой заливке, и у бедного шаблона досталась бы.
    background = next(role for role in roles if role.role is ColorRoleKind.BACKGROUND)
    slots = {parsed.theme.colors.get(ref).upper() for ref in TEXT_SLOTS}
    assert background.color_hex.upper() in slots, "фоном стала не тема, а случайная заливка"
    assert background.nearest_ref in TEXT_SLOTS
    assert any(role.role is ColorRoleKind.DOMINANT for role in roles)
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
        (pair.foreground_hex, pair.background_hex): pair for pair in derive(manifest).contrast_pairs
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


#: Гарнитуры каждого шаблона кейса по фактическому набору: семейство и то, где оно
#: встречено, — в порядке убывания доли знаков. Разобрано по самим файлам, а не
#: пересчитано кодом под тестом. У VK WorkSpace вторая гарнитура темы не набрала
#: ни одного знака — в факты она не попадает.
FONTS_IN_USE = {
    "VK Tech шаблон.pptx": [
        ("Play", True, False),
        ("Consolas", False, False),
        ("Arial", False, False),
    ],
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx": [("Play", False, False)],
    "Шаблон презентации VK Education.pptx": [
        ("Play", False, True),
        ("Arial", False, False),
        ("Consolas", False, False),
    ],
}


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_fonts_in_use_are_the_ones_the_examples_are_really_set_in(name: str) -> None:
    """Гарнитура по факту — та, которой набраны примеры, с долей знаков и местом набора."""
    parsed = TemplateParser().parse(case_template(name))

    fonts = derive(parsed).fonts_in_use

    assert [(font.family, font.in_titles, font.in_body) for font in fonts] == FONTS_IN_USE[name]
    assert [font.share for font in fonts] == sorted((font.share for font in fonts), reverse=True), (
        "гарнитуры идут по убыванию доли знаков"
    )
    assert round(sum(font.share for font in fonts), 2) == 1.0


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_font_the_theme_declares_is_not_the_one_the_template_is_set_in(name: str) -> None:
    """Смысл раздела: тема называет одну гарнитуру, а примеры набраны другой. У всех
    трёх шаблонов кейса это расходится — и страница показывает факт отдельно."""
    ds = derive(TemplateParser().parse(case_template(name)))

    assert ds.theme.major_font, "тема гарнитуру объявляет"
    assert ds.fonts_in_use[0].family.casefold() != ds.theme.major_font.casefold()


#: Три размера числа каждого шаблона кейса: старший кегль его KPI-компонента и две
#: ступени вниз по шкале шаблона. Разобрано по самим файлам: у VK Tech KPI набран
#: кеглем 32 при шкале 24 / 15,6 / 12 / 7,8 — ни один из трёх размеров не совпадает
#: с верхушкой шкалы, и подменить измеренное достройкой незаметно не выйдет.
NUMBER_SIZES = {
    "VK Tech шаблон.pptx": (32.0, 24.0, 15.6),
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx": (66.0, 36.0, 23.4),
    "Шаблон презентации VK Education.pptx": (36.0, 20.0, 18.0),
}


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_large_number_comes_from_the_kpi_component_of_the_template(name: str) -> None:
    """Крупное число — то, каким шаблон сам набрал показатель; средний и мелкий —
    ближайшие вниз по его же шкале кеглей."""
    parsed = TemplateParser().parse(case_template(name))

    sizes = derive(parsed).number_sizes

    assert (sizes.large_pt, sizes.medium_pt, sizes.small_pt) == NUMBER_SIZES[name]
    assert sizes.origin is Origin.MEASURED
    assert sizes.medium_pt in parsed.size_ladder_pt
    assert sizes.small_pt in parsed.size_ladder_pt


def test_without_a_kpi_component_the_three_sizes_are_the_top_of_the_ladder() -> None:
    """Шаблон, в котором показателей никто не рисовал, размеров числа не измерил:
    берутся три верхних кегля шкалы, и блок помечается достроенным."""
    parsed = TemplateParser().parse(case_template(CASE_TEMPLATES[0]))
    without_kpi = parsed.model_copy(
        update={
            "components": [
                component
                for component in parsed.components
                if component.kind is not ComponentKind.KPI
            ]
        }
    )

    sizes = derive(without_kpi).number_sizes

    assert (sizes.large_pt, sizes.medium_pt, sizes.small_pt) == tuple(parsed.size_ladder_pt[:3])
    assert sizes.origin is Origin.DERIVED
    assert sizes.large_pt != NUMBER_SIZES[CASE_TEMPLATES[0]][0], "измеренное и достроенное — разное"


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_catalogue_carries_over_every_component_the_parser_found(name: str) -> None:
    """Каталог элементов — перенос разобранного парсером, а не новый разбор: сколько
    повторяющихся элементов шаблон содержит, столько карточек и получает страница."""
    parsed = TemplateParser().parse(case_template(name))

    cards = derive(parsed).components

    assert len(cards) == len(parsed.components)
    assert {card.kind for card in cards} == {component.kind for component in parsed.components}
    assert all(card.seen_on for card in cards), "карточка без слайда ничем не подтверждена"
    assert all(card.repeats >= 3 for card in cards), "элемент — это то, что повторилось"
    assert all(card.origin is Origin.MEASURED for card in cards)


def test_a_kpi_card_keeps_the_proportions_and_the_sizes_of_the_template() -> None:
    """Карточка показателя VK Education: четыре штуки в ряд, значение 36 и подпись 16,
    заливка слотом темы, слайд 44. Разобрано по самому файлу."""
    parsed = TemplateParser().parse(case_template("Шаблон презентации VK Education.pptx"))

    card = next(card for card in derive(parsed).components if card.kind is ComponentKind.KPI)

    assert (card.repeats, card.axis) == (4, "row")
    assert card.text_sizes_pt == [36.0, 16.0]
    assert card.fill_ref is ColorRef.LT1
    assert card.fill_hex is None
    assert card.seen_on == [44]
    assert card.width_share == pytest.approx(0.2092, abs=0.0005)
    assert card.height_share == pytest.approx(0.2462, abs=0.0005)
    assert card.gap_share == pytest.approx(0.2332, abs=0.0005)


def test_a_pair_met_on_the_examples_stays_visible_next_to_the_same_pair_of_the_theme(
    manifest: TemplateManifest,
) -> None:
    """Пара темы — это объявление, пара с примера — факт о том, как шаблоном пользуются.
    Совпав по цветам, они не схлопываются в одну: иначе факт исчезает под объявлением."""
    base = _on_light_background(manifest)
    colors = base.theme.colors
    example = TemplateExample(
        slide_index=1,
        layout_id="L07",
        shapes=[
            _shape(
                "caption",
                base,
                width=0.5,
                height=0.5,
                kind=ShapeKind.TEXT,
                color_ref=ColorRef.DK1,
                text_len=20,
                size_pt=12.0,
            )
        ],
    )

    pairs = [
        pair
        for pair in derive(base.model_copy(update={"examples": [example]})).contrast_pairs
        if (pair.foreground_hex, pair.background_hex) == (colors.dk1, colors.lt1)
    ]

    assert [pair.from_theme for pair in pairs] == [True, False]


def test_the_marks_of_a_pair_do_not_depend_on_the_order_it_was_added(
    manifest: TemplateManifest,
) -> None:
    """Акцент, чей цвет совпал со слотом схемы, отметку «только для графики» не теряет:
    пара получает обе отметки — и риск темы, и негодность для длинного текста."""
    colors = manifest.theme.colors.model_copy(update={"dk1": DIM_GRAY, "accent1": DIM_GRAY})
    themed = manifest.model_copy(
        update={"theme": manifest.theme.model_copy(update={"colors": colors})}
    )

    pair = _pairs_by_colors(_with_one_example(themed))[(DIM_GRAY, colors.lt1)]

    assert pair.is_risk is True, "слот схемы на своём светлом не читается — противоречие темы"
    assert pair.display_only is True, "тот же цвет объявлен акцентом — в абзац он не годится"


def _many_combinations(manifest: TemplateManifest, count: int) -> TemplateManifest:
    """По слайду на сочетание: у каждого свой акцент, текст один и тот же."""
    manifest = _on_light_background(manifest)
    examples = [
        TemplateExample(
            slide_index=index,
            layout_id="L07",
            shapes=[
                _shape(
                    f"badge{index}",
                    manifest,
                    width=0.25,
                    height=0.25,
                    fill_hex=f"#{index:02X}00{index:02X}",
                ),
                _shape(
                    f"caption{index}",
                    manifest,
                    width=0.1,
                    height=0.1,
                    kind=ShapeKind.TEXT,
                    color_hex=GRAY,
                    text_len=20,
                    size_pt=12.0,
                ),
            ],
        )
        for index in range(1, count + 1)
    ]
    return manifest.model_copy(update={"examples": examples})


def test_the_tail_of_the_combinations_is_collapsed_into_one_entry(
    manifest: TemplateManifest,
) -> None:
    """Двенадцать троек — это не двенадцать полос раздела: то, что не попало в показанные,
    сходится в одну запись с суммарной долей и слайдами всех свёрнутых."""
    combinations = derive(_many_combinations(manifest, 12)).combinations

    tails = [
        combination
        for combination in combinations
        if combination.text_hex is None and combination.accent_hex is None
    ]
    assert len(tails) == 1, "хвост сворачивается ровно в одну запись"
    assert tails[0] is combinations[-1], "запись хвоста идёт последней"
    assert len(combinations) <= 9, "раздел не превращается в простыню"
    #: Допуск — накопленное округление долей до шестого знака, а не свобода ответа.
    assert tails[0].share == pytest.approx(len(tails[0].seen_on) / 12, abs=1e-5)
    assert round(sum(combination.share for combination in combinations), 3) == 1.0


def test_a_slide_without_text_and_without_an_accent_goes_into_the_tail(
    manifest: TemplateManifest,
) -> None:
    """Тройка без текста и без акцента — это один фон, а не сочетание: показывать в ней
    нечего, и она уходит в свёрнутую запись."""
    base = _with_one_example(manifest)
    plain = TemplateExample(
        slide_index=2,
        layout_id="L07",
        shapes=[_shape("plain", base, width=0.5, height=0.5, fill_ref=ColorRef.LT1)],
    )

    combinations = derive(
        base.model_copy(update={"examples": [base.examples[0], plain]})
    ).combinations

    assert len(combinations) == 2
    assert combinations[0].text_hex == GRAY, "настоящее сочетание осталось показанным"
    assert (combinations[-1].text_hex, combinations[-1].accent_hex) == (None, None)
    assert combinations[-1].seen_on == [2]


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_combinations_of_a_case_template_are_whole_and_bounded(name: str) -> None:
    """На настоящем шаблоне сочетания собираются по его же слайдам: доли в сумме дают
    единицу, каждое названо слайдами, и раздел не превращается в простыню."""
    parsed = TemplateParser().parse(case_template(name))

    combinations = derive(parsed).combinations
    slides = {example.slide_index for example in parsed.examples}

    assert combinations
    assert len(combinations) <= 9, "хвост сочетаний свёрнут"
    assert round(sum(item.share for item in combinations), 2) == 1.0
    assert all(item.seen_on for item in combinations)
    assert all(set(item.seen_on) <= slides for item in combinations)
    assert sum(len(item.seen_on) for item in combinations) == len(
        [example for example in parsed.examples if _background_of(parsed, example)]
    ), "каждый пример попал ровно в одно сочетание"


def _background_of(manifest: TemplateManifest, example: TemplateExample) -> str | None:
    """Фон макета примера — слайд без фона сочетания не даёт: читать текст не по чему."""
    layout = manifest.layout(example.layout_id) if example.layout_id else None
    return layout.background.color_hex if layout and layout.background else None


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_contrast_pairs_of_a_case_template_are_judged_by_wcag(name: str) -> None:
    """На настоящем шаблоне видны обе стороны: пары, объявленные темой, и пары,
    встреченные на примерах. Вердикт каждой сходится с порогами WCAG — 4,5 и 3,0."""
    pairs = derive(TemplateParser().parse(case_template(name))).contrast_pairs

    assert any(pair.from_theme for pair in pairs), "тема свои пары объявляет"
    assert any(not pair.from_theme for pair in pairs), "пары с примеров видны отдельно"
    for pair in pairs:
        assert pair.ratio >= 1.0
        if pair.level is ContrastLevel.AA:
            assert pair.ratio >= 4.5
        elif pair.level is ContrastLevel.AA_LARGE:
            assert 3.0 <= pair.ratio < 4.5
        else:
            assert pair.ratio < 3.0
        assert pair.from_theme or not pair.is_risk, "своих цветов шаблон не обещал"
        assert pair.level is not ContrastLevel.AA or not pair.display_only
