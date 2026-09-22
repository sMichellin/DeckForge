"""Шов `derive(manifest) -> DesignSystem`. Change `design-system-page`, таск 01.

Всё, что выражается числом, проверяется здесь: страница ничего не считает сама.
Ожидаемые величины берутся из манифеста и из спецификации, а не пересчитываются
тем же способом, что и код.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import Origin
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


def test_every_role_of_the_scale_is_in_the_ladder(manifest: TemplateManifest) -> None:
    ds = derive(manifest)

    assert [step.role for step in ds.typography.steps] == [
        TextRole.TITLE,
        TextRole.SUBTITLE,
        TextRole.BODY,
        TextRole.CAPTION,
    ]
    assert [step.size_pt for step in ds.typography.steps] == [40.0, 24.0, 18.0, 12.0]
    assert ds.typography.origin is Origin.MEASURED


def test_the_ladder_names_the_font_of_the_theme_and_the_purpose_of_the_role(
    manifest: TemplateManifest,
) -> None:
    ds = derive(manifest)
    title, subtitle = ds.typography.steps[0], ds.typography.steps[1]

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

    assert ds.typography.steps[0].width_share == 0.039856, "508 000 EMU на 12 746 000"
    assert ds.typography.steps[-1].width_share < ds.typography.steps[0].width_share


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


def test_the_fields_of_the_next_tasks_exist_and_start_empty(
    manifest: TemplateManifest,
) -> None:
    """Форма структуры решается здесь: таски 02 и 03 дописывают в готовые поля."""
    ds = derive(manifest)

    assert ds.palette_roles == []
    assert ds.combinations == []
    assert ds.contrast_pairs == []
    assert ds.fonts_in_use == []
    assert ds.components == []
    assert ds.synthesized == []
    assert ds.assembly_rules == []
    assert ds.number_sizes.large_pt is None
    assert ds.number_sizes.origin is Origin.DERIVED


def test_a_template_without_examples_does_not_break_derive(
    manifest: TemplateManifest,
) -> None:
    """Слайдов-примеров нет — разделы от темы и сетки строятся, измеряемые пусты."""
    bare = manifest.model_copy(update={"examples": [], "components": [], "usage": TemplateUsage()})

    ds = derive(bare)

    assert len(ds.typography.steps) == 4
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

    assert {step.role for step in ds.typography.steps} == {
        step.role for step in parsed.typography_scale
    }
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
