"""Шов `derive(manifest) -> DesignSystem`. Change `design-system-page`, таск 01.

Всё, что выражается числом, проверяется здесь: страница ничего не считает сама.
Ожидаемые величины берутся из манифеста и из спецификации, а не пересчитываются
тем же способом, что и код.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import DesignSystem, Origin, SpacingScale, TypeLevel
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import (
    BulletStyle,
    Margins,
    TemplateManifest,
    TemplateUsage,
)
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template
from tests.e2e.cold_corpus import cold_templates

#: Восемь уровней типографики, перечисленных заказчиком в образце дизайн-системы:
#: display, заголовок слайда, подзаголовок раздела, заголовок карточки, body large,
#: body, caption, label/tag. Порядок — сверху вниз, от крупного к мелкому.
EIGHT_LEVELS = [
    TypeLevel.DISPLAY,
    TypeLevel.SLIDE_TITLE,
    TypeLevel.SECTION_SUBTITLE,
    TypeLevel.CARD_TITLE,
    TypeLevel.BODY_LARGE,
    TypeLevel.BODY,
    TypeLevel.CAPTION,
    TypeLevel.LABEL,
]


def test_every_role_of_the_scale_is_in_the_ladder(manifest: TemplateManifest) -> None:
    """Каждая роль шкалы шаблона стоит на своей ступени лестницы с тем же кеглем."""
    ds = derive(manifest)
    measured = [step for step in ds.typography.steps if step.origin is Origin.MEASURED]

    assert [step.role for step in measured] == [
        TextRole.TITLE,
        TextRole.SUBTITLE,
        TextRole.BODY,
        TextRole.CAPTION,
    ]
    assert [step.size_pt for step in measured] == [40.0, 24.0, 18.0, 12.0]
    assert [step.level for step in measured] == [
        TypeLevel.SLIDE_TITLE,
        TypeLevel.SECTION_SUBTITLE,
        TypeLevel.BODY,
        TypeLevel.CAPTION,
    ]
    assert ds.typography.origin is Origin.MEASURED


def test_the_ladder_names_the_font_of_the_theme_and_the_purpose_of_the_role(
    manifest: TemplateManifest,
) -> None:
    ds = derive(manifest)
    by_level = {step.level: step for step in ds.typography.steps}
    title, subtitle = by_level[TypeLevel.SLIDE_TITLE], by_level[TypeLevel.SECTION_SUBTITLE]

    assert title.font_family == "TestSans Display", "major_latin темы"
    assert subtitle.font_family == "TestSans Text", "minor_latin темы"
    assert title.bold is True
    assert title.color_ref is ColorRef.DK1
    assert title.purpose, "назначение роли названо словами — иначе лестница немая"
    assert subtitle.purpose != title.purpose


def test_the_size_of_a_role_is_kept_as_a_share_of_the_slide_width(
    manifest: TemplateManifest,
) -> None:
    """Кегль 40 pt на слайде 12 746 000 EMU — это 3,99 % ширины (решение §9)."""
    ds = derive(manifest)

    by_level = {step.level: step for step in ds.typography.steps}

    assert by_level[TypeLevel.SLIDE_TITLE].width_share == 0.039856, "508 000 EMU на 12 746 000"
    assert (
        by_level[TypeLevel.LABEL].width_share < by_level[TypeLevel.SLIDE_TITLE].width_share
    )


def test_the_grid_repeats_the_numbers_of_the_manifest(manifest: TemplateManifest) -> None:
    ds = derive(manifest)
    grid = ds.grid

    assert grid.aspect == manifest.slide_size.aspect
    assert (grid.width_emu, grid.height_emu) == (12_746_000, 6_840_000)
    assert (grid.margins.left, grid.margins.top) == (720_000, 360_000)
    assert grid.columns == 12
    assert grid.content_width_emu == 12_746_000 - 2 * 720_000


def test_the_base_step_is_the_gutter_of_the_template(manifest: TemplateManifest) -> None:
    """Шаг сетки шаблона объявлен — берём его и помечаем измеренным."""
    spacing = derive(manifest).grid.spacing

    assert spacing.base_emu == 180_000
    assert spacing.origin is Origin.MEASURED
    assert spacing.steps_emu, "шкала кратностей не бывает пустой"
    assert spacing.steps_emu[0] == 180_000
    assert all(step % 180_000 == 0 for step in spacing.steps_emu)
    assert spacing.steps_in_margin == 2, "в поле 360 000 EMU укладываются два шага"


def test_without_a_gutter_the_step_is_the_common_divisor_of_the_margins(
    manifest: TemplateManifest,
) -> None:
    """Шаблон шага не объявил: он выводится из полей и помечается достроенным."""
    grid = manifest.grid.model_copy(update={"gutter_emu": 0})
    spacing = derive(manifest.model_copy(update={"grid": grid})).grid.spacing

    assert spacing.base_emu == 360_000, "НОД полей 720 000 и 360 000"
    assert spacing.origin is Origin.DERIVED


def test_coprime_margins_do_not_turn_the_step_into_one_emu(
    manifest: TemplateManifest,
) -> None:
    """Холодный шаблон «Шаблон презентации 2024»: НОД его полей равен 1 EMU.

    Шкала из единиц ничего не меряет, и достройка по ней получила бы радиус в одну
    тысячную миллиметра. Шагом становится наименьшее поле шаблона.
    """
    grid = manifest.grid.model_copy(
        update={
            "gutter_emu": 0,
            "margins_emu": Margins(left=1_143_000, right=1_143_000, top=260_350, bottom=260_351),
        }
    )
    spacing = derive(manifest.model_copy(update={"grid": grid})).grid.spacing

    assert spacing.base_emu == 260_350
    assert spacing.origin is Origin.DERIVED


def test_without_margins_the_step_falls_back_to_the_column_width(
    manifest: TemplateManifest,
) -> None:
    """Ни шага, ни полей — шаг всё равно ненулевой: на нём держится вся достройка."""
    grid = manifest.grid.model_copy(
        update={"gutter_emu": 0, "margins_emu": Margins(left=0, right=0, top=0, bottom=0)}
    )
    spacing = derive(manifest.model_copy(update={"grid": grid})).grid.spacing

    assert spacing.base_emu == 12_746_000 // 12
    assert spacing.origin is Origin.DERIVED


def test_the_marker_of_the_template_is_kept_with_its_slot_and_indents(
    manifest: TemplateManifest,
) -> None:
    bullet = BulletStyle(
        char="—",
        font="TestSans Text",
        color_ref=ColorRef.ACCENT1,
        margin_left_emu=180_000,
        indent_emu=-90_000,
    )
    ds = derive(manifest.model_copy(update={"bullet_levels": [bullet]}))

    assert ds.bullets.char == "—"
    assert ds.bullets.color_ref is ColorRef.ACCENT1
    assert (ds.bullets.margin_left_emu, ds.bullets.indent_emu) == (180_000, -90_000)
    assert ds.bullets.origin is Origin.MEASURED


def test_a_template_without_a_marker_gets_an_empty_block_marked_derived(
    manifest: TemplateManifest,
) -> None:
    """Шаблон маркера не задаёт — своего не дорисовываем: это был бы чужой дизайн."""
    ds = derive(manifest)

    assert ds.bullets.char is None
    assert ds.bullets.origin is Origin.DERIVED


def test_the_palette_carries_every_theme_slot_with_its_colour(
    manifest: TemplateManifest,
) -> None:
    """Единственное место структуры, где живут литеральные цвета, — значения слотов."""
    ds = derive(manifest)

    assert [slot.ref for slot in ds.theme.slots] == list(ColorRef)
    by_name = {slot.name: slot.color_hex for slot in ds.theme.slots}
    assert by_name["accent1"] == "#2E6BE6"
    assert by_name["dk1"] == "#101014"
    assert ds.theme.major_font == "TestSans Display"
    assert ds.theme.minor_font == "TestSans Text"
    assert ds.theme.origin is Origin.MEASURED


def test_one_structure_carries_the_fields_of_all_three_tasks(
    manifest: TemplateManifest,
) -> None:
    """Форма структуры решается здесь: таски 02 и 03 дописывают в готовые поля одной
    структуры, а не заводят рядом свои.

    Набор полей перечислен руками по спецификации таска 01, а не считан из модели:
    поле, пропавшее из структуры или переименованное, обязан заметить именно этот тест.
    """
    ds = derive(manifest)

    assert set(DesignSystem.model_fields) == {
        "template_id",
        "source_name",
        "typography",
        "grid",
        "bullets",
        "theme",
        "palette_roles",
        "combinations",
        "contrast_pairs",
        "fonts_in_use",
        "number_sizes",
        "components",
        "synthesized",
        "assembly_rules",
    }
    assert ds.typography.steps and ds.grid.spacing.steps_emu and ds.theme.slots, "таск 01"
    assert ds.contrast_pairs, "измеренное таском 02 лежит в той же структуре"
    assert ds.synthesized and ds.assembly_rules, "достроенное таском 03 — там же"


def test_a_template_without_examples_does_not_break_derive(
    manifest: TemplateManifest,
) -> None:
    """Слайдов-примеров нет — разделы от темы и сетки строятся, измеряемые пусты."""
    bare = manifest.model_copy(update={"examples": [], "components": [], "usage": TemplateUsage()})

    ds = derive(bare)

    assert len(ds.typography.steps) == len(EIGHT_LEVELS)
    assert ds.grid.spacing.steps_emu
    assert ds.theme.slots
    assert (ds.palette_roles, ds.combinations, ds.fonts_in_use) == ([], [], [])


def test_every_filled_block_says_where_it_came_from(manifest: TemplateManifest) -> None:
    """Метка «измерено / достроено» живёт в данных, а не в разметке страницы."""
    ds = derive(manifest)
    blocks = [ds.typography, ds.grid, ds.grid.spacing, ds.bullets, ds.theme, ds.number_sizes]

    assert all(isinstance(block.origin, Origin) for block in blocks)
    assert all(isinstance(step.origin, Origin) for step in ds.typography.steps)
    assert ds.typography.origin is Origin.MEASURED
    assert ds.bullets.origin is Origin.DERIVED, "маркера в шаблоне нет — это достройка"


def test_two_calls_on_one_manifest_give_equal_structures(
    manifest: TemplateManifest,
) -> None:
    """G01: страница детерминированна, значит и структура под ней тоже."""
    first, second = derive(manifest), derive(manifest)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


CASE_TEMPLATES = [
    "VK Tech шаблон.pptx",
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
    "Шаблон презентации VK Education.pptx",
]


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_case_templates_give_a_design_system(name: str) -> None:
    """Структура собирается на настоящих шаблонах, а не только на синтетическом."""
    parsed = TemplateParser().parse(case_template(name), use_cache=False)

    ds = derive(parsed)

    assert [step.level for step in ds.typography.steps] == EIGHT_LEVELS
    measured = {
        step.role: step.size_pt
        for step in ds.typography.steps
        if step.origin is Origin.MEASURED
    }
    assert measured == {step.role: step.size_pt for step in parsed.typography_scale}
    assert all(step.size_pt in parsed.size_ladder_pt for step in ds.typography.steps), (
        "кегль вне шкалы шаблона — правило 6"
    )
    assert all(step.width_share > 0 for step in ds.typography.steps)
    assert len(ds.theme.slots) == len(list(ColorRef))
    assert ds.grid.spacing.base_emu > 0
    assert ds.grid.spacing.steps_emu
    assert ds.grid.content_width_emu <= parsed.slide_size.cx_emu
    assert derive(parsed) == ds, "второй вызов на том же манифесте дал другое"


def test_a_cold_template_gives_a_design_system_too() -> None:
    """Правило 10: незнакомый шаблон проверяется наравне с шаблонами кейса."""
    cold = cold_templates()
    if not cold:
        pytest.skip("холодного корпуса на этой машине нет")

    for path in cold[:2]:
        ds = derive(TemplateParser().parse(path, use_cache=False))

        assert ds.theme.slots, f"{path.name}: палитра пуста"
        assert ds.grid.spacing.base_emu > 0, f"{path.name}: базовый шаг нулевой"


def test_the_ladder_carries_all_eight_levels_of_the_brief(manifest: TemplateManifest) -> None:
    """Заказчик назвала восемь уровней — лестница несёт все восемь, а не четыре роли домена.

    Четыре уровня совпадают с ролями шкалы шаблона и помечены измеренными; остальные
    четыре достроены и помечены достроенными.
    """
    ds = derive(manifest)

    assert [step.level for step in ds.typography.steps] == EIGHT_LEVELS
    measured = {
        step.level: step.size_pt
        for step in ds.typography.steps
        if step.origin is Origin.MEASURED
    }
    assert measured == {
        TypeLevel.SLIDE_TITLE: 40.0,
        TypeLevel.SECTION_SUBTITLE: 24.0,
        TypeLevel.BODY: 18.0,
        TypeLevel.CAPTION: 12.0,
    }, "кегли ролей шкалы шаблона остаются измеренными и не меняются"
    derived = {step.level for step in ds.typography.steps if step.origin is Origin.DERIVED}
    assert derived == {
        TypeLevel.DISPLAY,
        TypeLevel.CARD_TITLE,
        TypeLevel.BODY_LARGE,
        TypeLevel.LABEL,
    }
    assert len({step.purpose for step in ds.typography.steps}) == 8, (
        "у каждого уровня своё назначение словами — иначе лестница немая"
    )


def test_a_scale_shorter_than_the_ladder_takes_only_steps_of_the_template(
    manifest: TemplateManifest,
) -> None:
    """Ступеней в шаблоне меньше, чем уровней: лишние берут ступень шкалы, а не число из головы.

    Шкала из двух кеглей — 40 и 12 pt. Восемь уровней всё равно собираются, и каждый
    несёт один из этих двух кеглей (правило 6). Уровень повторяет кегль той ступени,
    чей вид наследует: заголовочные держат 40, текстовые прижимаются к подписи — 12.
    """
    scale = [
        step
        for step in manifest.typography_scale
        if step.role in (TextRole.TITLE, TextRole.CAPTION)
    ]
    short = manifest.model_copy(update={"typography_scale": scale})

    ds = derive(short)
    sizes = [step.size_pt for step in ds.typography.steps]

    assert [step.level for step in ds.typography.steps] == EIGHT_LEVELS
    assert set(sizes) <= set(short.size_ladder_pt), "кегль, которого нет в шкале шаблона"
    assert sizes == sorted(sizes, reverse=True), "лестница обязана не возрастать"
    assert sizes == [40.0, 40.0, 40.0, 40.0, 12.0, 12.0, 12.0, 12.0], (
        "заголовочные уровни держат крупную ступень, текстовые — подпись"
    )
    origins = {step.level: step.origin for step in ds.typography.steps}
    assert origins[TypeLevel.SLIDE_TITLE] is Origin.MEASURED
    assert origins[TypeLevel.CAPTION] is Origin.MEASURED
    assert origins[TypeLevel.SECTION_SUBTITLE] is Origin.DERIVED, (
        "подзаголовка в шкале нет — уровень достроен и обязан это сказать"
    )


def test_the_grid_is_measured_even_when_the_guides_are_inferred(
    manifest: TemplateManifest,
) -> None:
    """Направляющие выведены — но формат и пропорции из `slide_size` измерены всегда.

    Метка блока говорит про то, что в блоке измерено. Одна метка на весь раздел
    объявила бы достроенными и формат, и пропорции — а их никто не выводил.
    Про выведенные направляющие говорит отдельная метка.
    """
    grid = manifest.grid.model_copy(update={"guides_source": "inferred"})
    inferred = derive(manifest.model_copy(update={"grid": grid})).grid

    assert inferred.origin is Origin.MEASURED, "формат и пропорции сняты со слайда"
    assert inferred.guides_origin is Origin.DERIVED, "направляющие выведены кластеризацией"

    from_xml = derive(manifest).grid
    assert manifest.grid.guides_source == "xml"
    assert from_xml.origin is Origin.MEASURED
    assert from_xml.guides_origin is Origin.MEASURED


def test_the_description_of_base_source_names_exactly_what_derive_can_give(
    manifest: TemplateManifest,
) -> None:
    """Метку `base_source` читает таск 04 из другого контекста — по описанию поля.

    Описание перечисляет значения «имя — пояснение» через точку с запятой. Набор имён
    в описании обязан совпадать с набором, который отдаёт `derive`: иначе следующий
    читатель будет ветвиться по значению, которого не бывает, и не обработает то,
    которое бывает.
    """
    no_gutter = manifest.grid.model_copy(update={"gutter_emu": 0})
    coprime = no_gutter.model_copy(
        update={
            "margins_emu": Margins(left=1_143_000, right=1_143_000, top=260_350, bottom=260_351)
        }
    )
    no_margins = no_gutter.model_copy(
        update={"margins_emu": Margins(left=0, right=0, top=0, bottom=0)}
    )
    given = {
        derive(manifest.model_copy(update={"grid": grid})).grid.spacing.base_source
        for grid in (manifest.grid, no_gutter, coprime, no_margins)
    }
    described = {
        clause.split("—")[0].strip()
        for clause in SpacingScale.model_fields["base_source"].description.split(";")  # type: ignore[union-attr]
    }

    assert given == {"gutter", "margins_gcd", "margin", "columns"}, "набор значений изменился"
    assert described == given, "описание поля разошлось с тем, что отдаёт derive"
