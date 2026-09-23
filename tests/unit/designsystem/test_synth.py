"""Достроенное из примитивов шаблона. Change `design-system-page`, таск 03.

Шов тот же, что и у таска 01, — `derive(manifest) -> DesignSystem`: страница ничего
не считает сама, и всё, что выражается числом, проверяется здесь.

Ожидаемые величины берутся из синтетического манифеста (`tests/conftest.py`) и из
спецификации, а не пересчитываются тем же способом, что и код: базовый шаг шаблона —
180 000 EMU (шаг сетки), кегли шкалы — 40 / 24 / 18 / 12 pt, поля — 720 000 по бокам
и 360 000 сверху и снизу.
"""

from __future__ import annotations

import json

import pytest

from deckforge.config import ASSETS_DIR
from deckforge.designsystem import derive
from deckforge.designsystem.models import Origin
from deckforge.domain.enums import ColorRef
from deckforge.domain.template import (
    BulletStyle,
    ComponentKind,
    ComponentSpec,
    Decor,
    DecorElement,
    FooterSpec,
    TemplateManifest,
    TemplateUsage,
)
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template

BASE_EMU = 180_000
CAPTION_PT = 12.0
BODY_PT = 18.0

ACCENT_REFS = [
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
]


def group(manifest: TemplateManifest, name: str) -> list:
    return [element for element in derive(manifest).synthesized if element.group == name]


def test_the_labels_section_is_built_from_the_theme_and_the_scale(
    manifest: TemplateManifest,
) -> None:
    """R08: метка раздела, теги категорий, круглые бейджи — цветом слота и кеглем шкалы."""
    labels = group(manifest, "плашки")

    assert {element.kind for element in labels} == {"section_label", "tag", "badge"}
    assert all(element.origin is Origin.DERIVED for element in labels)

    label = next(element for element in labels if element.kind == "section_label")
    assert label.size_pt == CAPTION_PT, "мелкий кегль — из типошкалы шаблона"
    assert label.text == label.text.upper(), "метка раздела — верхним регистром"
    assert label.color_ref in ACCENT_REFS


def test_a_tag_is_built_for_every_accent_slot_the_theme_really_has(
    manifest: TemplateManifest,
) -> None:
    """Тег — на каждый акцент темы; одинаковые по цвету акценты не дублируются."""
    tags = [element for element in group(manifest, "плашки") if element.kind == "tag"]

    assert [tag.color_ref for tag in tags] == ACCENT_REFS, "шесть разных акцентов темы"
    assert all(tag.size_pt == CAPTION_PT for tag in tags)

    theme = manifest.theme.colors
    one_accent = theme.model_copy(update={f"accent{n}": theme.accent1 for n in range(2, 7)})
    flat = manifest.model_copy(
        update={"theme": manifest.theme.model_copy(update={"colors": one_accent})}
    )
    flat_tags = [element for element in group(flat, "плашки") if element.kind == "tag"]

    assert [tag.color_ref for tag in flat_tags] == [ColorRef.ACCENT1], "один цвет — один тег"


def test_badges_are_three_circles_multiple_of_the_base_step(
    manifest: TemplateManifest,
) -> None:
    """«Круги трёх размеров, кратных базовому шагу»: 2, 3 и 4 шага сетки шаблона."""
    badges = [element for element in group(manifest, "плашки") if element.kind == "badge"]

    assert [badge.spacing_emu for badge in badges] == [
        2 * BASE_EMU,
        3 * BASE_EMU,
        4 * BASE_EMU,
    ]
    assert [badge.radius_emu for badge in badges] == [badge.spacing_emu // 2 for badge in badges]
    scale = {step.size_pt for step in manifest.typography_scale}
    sizes = [badge.size_pt for badge in badges]
    assert set(sizes) <= scale, "кегль бейджа — только из типошкалы шаблона"
    assert sizes == sorted(sizes), "чем крупнее круг, тем крупнее кегль"
    assert len({badge.title for badge in badges}) == 3, "у каждого размера своя подпись"


def test_three_list_styles_are_built_each_with_a_purpose(
    manifest: TemplateManifest,
) -> None:
    """R09: маркированный, нумерованный, иконочный — у каждого подпись, для чего он."""
    lists = group(manifest, "списки")

    assert {element.kind for element in lists} == {"bulleted", "numbered", "icon"}
    assert all(element.purpose for element in lists), "стиль без подписи не объясняет себя"
    assert len({element.purpose for element in lists}) == 3, "подписи разные, а не одна на всех"

    numbered = next(element for element in lists if element.kind == "numbered")
    assert numbered.origin is Origin.DERIVED
    assert numbered.radius_emu == numbered.spacing_emu // 2, "номер в круге"
    assert numbered.size_pt == BODY_PT


def test_the_bulleted_style_carries_the_marker_the_template_really_declares(
    manifest: TemplateManifest,
) -> None:
    """Знак шаблона — `measured`; шаблон без маркера — `derived` и без выдуманной точки."""
    marked = manifest.model_copy(
        update={
            "bullet_levels": [
                BulletStyle(char="—", font="TestSans Text", color_ref=ColorRef.ACCENT2)
            ]
        }
    )
    with_marker = next(element for element in group(marked, "списки") if element.kind == "bulleted")

    assert with_marker.text == "—"
    assert with_marker.color_ref is ColorRef.ACCENT2, "цвет маркера — слотом шаблона"
    assert with_marker.origin is Origin.MEASURED

    without = next(element for element in group(manifest, "списки") if element.kind == "bulleted")

    assert without.text == "", "маркера в шаблоне нет — своего не дорисовываем"
    assert without.origin is Origin.DERIVED


def test_the_icon_style_names_icons_that_really_exist_in_the_assets(
    manifest: TemplateManifest,
) -> None:
    """Имена иконок — из `assets/icons/lucide`: файлы подставит страница, не этот слой."""
    icons = [element for element in group(manifest, "списки") if element.kind == "icon"]
    nodes = json.loads(
        (ASSETS_DIR / "icons" / "lucide" / "icon-nodes.json").read_text(encoding="utf-8")
    )

    assert icons, "иконочный список без иконок"
    assert all(element.text in nodes for element in icons), "имя иконки не из набора lucide"
    assert len({element.text for element in icons}) == len(icons), "иконки не повторяются"


def test_four_dividers_are_built_and_their_weight_is_a_fraction_of_the_step(
    manifest: TemplateManifest,
) -> None:
    """R11: четыре вида разделителей; толщина — доля базового шага, а не пиксели."""
    dividers = {
        element.kind: element
        for element in group(manifest, "элементы")
        if element.kind.startswith("divider")
    }

    assert set(dividers) == {
        "divider_thin",
        "divider_accent",
        "divider_dashed",
        "divider_quote_bar",
    }
    assert dividers["divider_thin"].line_emu == BASE_EMU // 8
    assert dividers["divider_accent"].line_emu == BASE_EMU // 4
    assert dividers["divider_dashed"].line_emu == BASE_EMU // 8
    assert dividers["divider_quote_bar"].line_emu == BASE_EMU // 2
    assert dividers["divider_thin"].color_ref is ColorRef.LT2, "тонкий — по цвету рамки"
    assert dividers["divider_accent"].color_ref in ACCENT_REFS
    assert all(element.origin is Origin.DERIVED for element in dividers.values())


def test_pagination_is_built_on_three_backgrounds_with_readable_digits(
    manifest: TemplateManifest,
) -> None:
    """Ролей цвета ещё нет — фоны берутся слотами lt1, accent1, dk1, цифра читается на каждом."""
    pagination = [
        element for element in group(manifest, "элементы") if element.kind == "pagination"
    ]

    assert [element.on_color_ref for element in pagination] == [
        ColorRef.LT1,
        ColorRef.ACCENT1,
        ColorRef.DK1,
    ]
    assert len({element.title for element in pagination}) == 3, "у каждого фона своя подпись"
    on_light, _, on_dark = pagination
    assert on_light.color_ref is ColorRef.DK1, "на белом #FFFFFF читается тёмный слот"
    assert on_dark.color_ref is ColorRef.LT1, "на тёмном #101014 читается светлый слот"
    assert on_light.size_pt == CAPTION_PT


def test_the_header_and_the_footer_repeat_what_the_decor_of_the_template_says(
    manifest: TemplateManifest,
) -> None:
    """Шапка и подвал — из `manifest.decor`: есть ли логотип, где он и на какой высоте подвал."""
    slide = manifest.slide_size
    logo = DecorElement(
        layout_ids=["L01"],
        x=slide.cx_emu - 2 * BASE_EMU,
        y=BASE_EMU,
        cx=BASE_EMU,
        cy=BASE_EMU,
    )
    decorated = manifest.model_copy(
        update={"decor": Decor(logo=logo, footer=FooterSpec(present=True, y_emu=6 * BASE_EMU))}
    )
    elements = {
        element.kind: element
        for element in group(decorated, "элементы")
        if element.kind in {"header", "footer"}
    }

    assert elements["header"].spacing_emu == BASE_EMU, "логотип стоит на этой высоте"
    assert "справа" in elements["header"].purpose, "логотип в правой половине слайда"
    assert elements["footer"].spacing_emu == 6 * BASE_EMU

    bare = {
        element.kind: element
        for element in group(manifest, "элементы")
        if element.kind in {"header", "footer"}
    }

    assert set(bare) == {"header", "footer"}, "разделы строятся и у шаблона без декора"
    assert bare["header"].spacing_emu is None
    assert "нет" in bare["footer"].purpose, "подвала в шаблоне нет — так и сказано"


def test_the_table_the_quote_and_two_callouts_are_built_in_the_colours_of_the_template(
    manifest: TemplateManifest,
) -> None:
    """R12, R13: таблица с чередованием и дельтами, цитата с полосой, два callout."""
    elements = {element.kind: element for element in group(manifest, "элементы")}

    assert {
        "table_header",
        "table_row_alt",
        "table_delta_up",
        "table_delta_down",
        "quote",
        "callout_insight",
        "callout_risk",
    } <= set(elements)

    assert elements["table_header"].color_ref is ColorRef.ACCENT1, "заголовок — цветом доминанты"
    assert elements["table_row_alt"].color_ref is ColorRef.LT2, "чередование — светлым слотом"
    deltas = (elements["table_delta_up"].color_ref, elements["table_delta_down"].color_ref)
    assert all(delta in ACCENT_REFS for delta in deltas), "дельты — акцентами"
    assert deltas[0] is not deltas[1], "рост и падение не одного цвета"

    quote = elements["quote"]
    assert quote.line_emu == BASE_EMU // 2, "полоса цитаты — та же доля базового шага"
    assert quote.color_ref in ACCENT_REFS

    insight, risk = elements["callout_insight"], elements["callout_risk"]
    assert insight.color_ref is not risk.color_ref, "«инсайт» и «риск» — на разных акцентах"
    assert {insight.color_ref, risk.color_ref} <= set(ACCENT_REFS)
    assert insight.radius_emu == BASE_EMU // 4, "радиус — доля шага, а не пиксели из головы"
    assert all(element.origin is Origin.DERIVED for element in (quote, insight, risk))


def test_the_rule_that_meaning_is_not_only_colour_is_written_and_marked_derived(
    manifest: TemplateManifest,
) -> None:
    """R28, история 10b: правило доступности — строкой в разделе, помечено достроенным.

    Change `a-minimum-is-not-a-norm` добавил рядом ещё три правила заказчика; проверка
    здесь по-прежнему про это одно, но раздел больше не единственный его житель.
    """
    accessibility = group(manifest, "доступность")
    kinds = [element.kind for element in accessibility]

    assert kinds[0] == "meaning_beyond_colour", "правило про цвет — первым в разделе"
    assert {"minimum_is_not_a_norm", "ink_follows_the_plate", "the_real_background"} <= set(kinds)
    rule = accessibility[0]
    assert "цвет" in rule.text.lower(), "правило названо словами, а не подразумевается"
    assert rule.purpose
    assert rule.origin is Origin.DERIVED, "это правило, а не измерение"


def rules(manifest: TemplateManifest) -> dict[str, float]:
    return {rule.source: rule.value for rule in derive(manifest).assembly_rules}


def test_every_assembly_rule_carries_a_number_taken_from_the_manifest(
    manifest: TemplateManifest,
) -> None:
    """R29: правило без числа из шаблона — чужой совет, и на страницу оно не идёт."""
    assembly = derive(manifest).assembly_rules

    assert assembly, "раздел правил сборки пуст"
    assert all(rule.value > 0 for rule in assembly), "правило без числа на страницу не идёт"
    assert all(rule.text and rule.source for rule in assembly)
    assert all(rule.origin is Origin.DERIVED for rule in assembly)

    by_source = rules(manifest)
    assert by_source["grid.margins_emu"] == 360_000, "наименьшее ненулевое поле шаблона"
    assert by_source["grid.gutter_emu"] == BASE_EMU, "кратность отступов — базовый шаг"
    assert by_source["layouts.capacity.max_bullets"] == 6, "вместимость самого частого тела"
    assert "components.repeats" not in by_source, "компонентов нет — правила о карточках нет"


def test_the_rule_about_cards_in_a_row_comes_from_the_components_of_the_template(
    manifest: TemplateManifest,
) -> None:
    """Сколько карточек ставить в ряд — из `components.repeats`, а не из вкуса."""
    kpi = ComponentSpec(
        kind=ComponentKind.KPI,
        repeats=4,
        axis="row",
        width_share=0.2,
        height_share=0.15,
        gap_share=0.02,
        seen_on=[3, 5],
    )
    with_components = manifest.model_copy(update={"components": [kpi]})

    assert rules(with_components)["components.repeats"] == 4


def test_a_bare_template_still_gets_every_section(manifest: TemplateManifest) -> None:
    """R16: ни примеров, ни компонентов, ни декора — разделы всё равно построены."""
    bare = manifest.model_copy(
        update={
            "examples": [],
            "components": [],
            "usage": TemplateUsage(),
            "decor": Decor(),
            "bullet_levels": [],
        }
    )
    ds = derive(bare)

    assert {element.group for element in ds.synthesized} == {
        "плашки",
        "списки",
        "элементы",
        "доступность",
    }
    assert ds.assembly_rules, "правила сборки строятся и без компонентов"
    assert all(element.origin is Origin.DERIVED for element in ds.synthesized)


CASE_TEMPLATES = [
    "VK Tech шаблон.pptx",
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
    "Шаблон презентации VK Education.pptx",
]


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_a_real_template_is_built_only_from_its_own_slots_sizes_and_step(name: str) -> None:
    """Настоящий шаблон: каждый цвет — его слот, каждый кегль — его шкала, размеры — доли
    его шага. Числа «из головы» тут и видно."""
    parsed = TemplateParser().parse(case_template(name), use_cache=False)
    ds = derive(parsed)

    scale = {step.size_pt for step in parsed.typography_scale}
    slots = {slot.ref for slot in ds.theme.slots}
    base = ds.grid.spacing.base_emu

    assert {element.group for element in ds.synthesized} == {
        "плашки",
        "списки",
        "элементы",
        "доступность",
    }
    assert all(element.size_pt in scale for element in ds.synthesized if element.size_pt)
    assert all(element.color_ref in slots for element in ds.synthesized if element.color_ref)
    assert all(0 < element.line_emu <= base for element in ds.synthesized if element.line_emu)
    assert all(element.radius_emu > 0 for element in ds.synthesized if element.radius_emu)
    assert all(rule.value > 0 for rule in ds.assembly_rules)


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_a_real_template_without_components_and_examples_keeps_every_section(
    name: str,
) -> None:
    """Автор шаблона не нарисовал ни примеров, ни повторяющихся элементов — разделы всё
    равно полные: дизайн-система достраивается из примитивов."""
    parsed = TemplateParser().parse(case_template(name), use_cache=False)
    stripped = parsed.model_copy(update={"components": [], "examples": []})

    ds = derive(stripped)

    assert {element.group for element in ds.synthesized} == {
        "плашки",
        "списки",
        "элементы",
        "доступность",
    }
    assert ds.assembly_rules
    assert not [rule for rule in ds.assembly_rules if rule.source == "components.repeats"]
