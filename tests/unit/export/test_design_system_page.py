"""Шов `render(ds) -> str`. Change `design-system-page`, таск 04.

Страница ничего не считает сама: числа приходят из `derive`, и на них есть свои тесты.
Здесь проверяется то, что относится к странице как к документу: состав разделов,
самодостаточность (её проверяет заказчик двойным кликом без интернета), запрет
литеральных цветов вне `:root` и побайтная повторяемость.
"""

from __future__ import annotations

import re

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import DesignSystem, Origin
from deckforge.domain.template import TemplateManifest
from deckforge.export.design_system_page import render
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template

#: Семь разделов образца заказчика, сверху вниз. Номера — из образца, а не наши.
#: Метка измеренного блока и образец строки лестницы — как их печатает страница.
MEASURED_LABEL = "измерено в шаблоне"
SAMPLE_TEXT = "Съешь ещё этих мягких французских булок"

SECTIONS = [
    "02 — Семантика и сочетания",
    "03 — Доступность",
    "04 — Типографика",
    "05 — Плашки и метки",
    "06 — Буллеты и списки",
    "07 — Базовые элементы слайда",
    "08 — Сетка и модуль слайда",
]


@pytest.fixture
def ds(manifest: TemplateManifest) -> DesignSystem:
    return derive(manifest)


def test_seven_sections_stand_in_the_order_of_the_sample(ds: DesignSystem) -> None:
    """Все семь разделов образца на месте и идут сверху вниз в его порядке."""
    html = render(ds)

    positions = [html.find(title) for title in SECTIONS]

    assert all(pos >= 0 for pos in positions), [
        title for title, pos in zip(SECTIONS, positions, strict=True) if pos < 0
    ]
    assert positions == sorted(positions)


#: Ссылка наружу в любом виде. Страницу открывают двойным кликом без интернета:
#: любой из этих кусков означает, что что-то не загрузится и блок окажется пустым.
EXTERNAL = re.compile(r"https?://|//cdn|url\s*\(\s*['\"]?(?!data:)[a-z]|@import|<link|<script")

#: Литеральный цвет: #RGB, #RRGGBB, #RRGGBBAA, rgb(…), hsl(…).
LITERAL_COLOR = re.compile(
    r"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b|\brgba?\s*\(|\bhsla?\s*\("
)
ROOT_BLOCK = re.compile(r":root\s*\{.*?\}", re.DOTALL)
STYLE_ATTR = re.compile(r'style="([^"]*)"')
STYLE_TAG = re.compile(r"<style>(.*?)</style>", re.DOTALL)


def styling_of(html: str) -> str:
    """Всё, чем страница красится: содержимое `<style>` без `:root` и все `style="…"`."""
    css = "\n".join(ROOT_BLOCK.sub("", block) for block in STYLE_TAG.findall(html))
    return css + "\n" + "\n".join(STYLE_ATTR.findall(html))


def test_page_has_no_link_to_the_outside(ds: DesignSystem) -> None:
    """Ни шрифта, ни скрипта, ни картинки по URL: страница открывается без интернета."""
    html = render(ds)

    assert EXTERNAL.search(html) is None, EXTERNAL.search(html)


def test_literal_colours_live_only_in_the_root_block(ds: DesignSystem) -> None:
    """Красится страница только через `var(…)`: литералы стоят одним блоком в `:root`.

    Шестнадцатеричный код цвета, напечатанный человеку как текст, — это данные шаблона,
    а не способ покраски, и под правило не подпадает.
    """
    html = render(ds)

    assert LITERAL_COLOR.search(styling_of(html)) is None, LITERAL_COLOR.search(styling_of(html))
    assert ROOT_BLOCK.search(html) is not None


def test_origin_label_follows_the_flag_in_the_data(ds: DesignSystem) -> None:
    """Метка происхождения читается из данных, а не проставлена в разметке руками."""
    measured_steps = [step for step in ds.typography.steps if step.origin is Origin.MEASURED]
    assert measured_steps, "фикстура должна давать хотя бы одну измеренную ступень"

    before = render(ds).count(MEASURED_LABEL)
    derived_steps = [
        step.model_copy(update={"origin": Origin.DERIVED}) for step in ds.typography.steps
    ]
    flipped = ds.model_copy(
        update={"typography": ds.typography.model_copy(update={"steps": derived_steps})}
    )

    assert render(flipped).count(MEASURED_LABEL) == before - len(measured_steps)


def test_type_ladder_is_shown_in_the_proportion_of_the_template(ds: DesignSystem) -> None:
    """Кегль образца — доля ширины слайда, а не пиксели.

    Заголовок синтетического шаблона — 40 pt на слайде шириной 12 746 000 EMU,
    то есть 508 000 / 12 746 000 ≈ 3,9856 % ширины.
    """
    html = render(ds)

    assert "3.9856cqw" in html
    assert html.count(SAMPLE_TEXT) == len(ds.typography.steps)
    assert "container-type: inline-size" in html


def test_slide_anatomy_is_drawn_by_the_numbers_of_the_grid(ds: DesignSystem) -> None:
    """Схема слайда — проценты от его сторон: 2 см левого поля на слайде 12 746 000 EMU."""
    html = render(ds)

    assert f"aspect-ratio: {ds.grid.width_emu} / {ds.grid.height_emu}" in html
    assert "left: 5.6488%" in html


def test_two_renders_of_the_same_structure_are_byte_equal(ds: DesignSystem) -> None:
    """Без модели и без времени генерации: страница повторяется побайтно (G01)."""
    assert render(ds).encode("utf-8") == render(ds).encode("utf-8")


@pytest.mark.parametrize(
    "name",
    [
        "VK Tech шаблон.pptx",
        "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
        "Шаблон презентации VK Education.pptx",
    ],
)
def test_page_of_a_real_template_holds_the_same_contract(name: str) -> None:
    """На настоящем шаблоне — те же семь разделов, ни ссылок наружу, ни литералов в покраске."""
    manifest = TemplateParser().parse(case_template(name))

    html = render(derive(manifest))

    assert all(title in html for title in SECTIONS)
    assert EXTERNAL.search(html) is None
    assert LITERAL_COLOR.search(styling_of(html)) is None


# --- change `a-minimum-is-not-a-norm` -------------------------------------------


def test_the_contrast_table_names_the_threshold_of_every_pair(ds: DesignSystem) -> None:
    """Порог на странице виден рядом с коэффициентом: иначе «4,6» ничего не говорит."""
    html = render(ds)

    assert '<th class="num">Нужно</th>' in html
    assert "Порог зависит от роли текста" in html


def test_a_pair_without_a_margin_is_called_tight(manifest: TemplateManifest) -> None:
    """«Минимум — не норма»: пара, взявшая минимум без запаса, помечена словами."""
    colors = manifest.theme.colors.model_copy(update={"dk1": "#767676", "lt1": "#FFFFFF"})
    theme = manifest.theme.model_copy(update={"colors": colors})
    html = render(derive(manifest.model_copy(update={"theme": theme})))

    assert "впритык" in html
    assert "для подписи и сноски не брать" in html


def test_the_page_says_where_the_template_has_no_readable_pair(ds: DesignSystem) -> None:
    """Раздел есть всегда: «таких мест нет» — это тоже ответ, и он честный."""
    html = render(ds)

    assert "Места без читаемой пары" in html
    assert "Таких мест нет" in html


def test_the_page_shows_the_defects_of_a_template_that_reads_nowhere(
    manifest: TemplateManifest,
) -> None:
    """Нарушитель к предыдущему: шаблон из полутонов получает таблицу дефектов."""
    from deckforge.domain.enums import ColorRef

    colors = manifest.theme.colors.model_copy(update={ref.value: "#8A8A8A" for ref in ColorRef})
    theme = manifest.theme.model_copy(update={"colors": colors})
    html = render(derive(manifest.model_copy(update={"theme": theme})))

    assert "Лучшее в теме" in html
    assert "Таких мест нет" not in html


def test_the_rules_of_the_customer_stand_next_to_the_numbers(ds: DesignSystem) -> None:
    """Три правила из разбора заказчика — на странице, рядом с таблицами."""
    html = render(ds)

    assert "Минимум — не норма" in html
    assert "Цвет текста выбирает плашка" in html
    assert "Фон считается настоящий" in html
