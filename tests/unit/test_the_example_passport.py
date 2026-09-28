"""Паспорт строится по примеру. Change `the-example-passport` (план Б, шаг 1б, ADR-009).

На прогоне 28.09 пример VK Tech `ex018` занял 6 слайдов из 10, и его карточки стояли
пустыми. Каталог принял за повтор **ряд** карточек, а не карточку: сетка 3 + 2 читалась
как «два повтора». Паспорт находит карточку по подложке — фигуре без текста, в которой
лежат тексты, — и только без подложки берёт повтор каталога.

Замер здесь — подделка `fits` по длине текста: модульный тест не зависит от шрифтов
образа. Вписывание шрифтом проверяет тест на холодном корпусе (`tests/e2e`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deckforge.composition import passport as module
from deckforge.composition.passport import (
    build_passport,
    capacity,
    sample,
    sample_number,
    with_passports,
)
from deckforge.designsystem.models import (
    DesignSystem,
    PlaceKind,
    Recipe,
    RecipeKind,
    TypeLevel,
    Zone,
)
from deckforge.domain.template import ExampleShape, ShapeKind, TemplateExample

SLIDE_AREA = 12_000_000 * 6_750_000
CM = 360_000


def shape(
    xml_id: int, x: float, y: float, cx: float, cy: float, *, z: int, text: int = 0
) -> ExampleShape:
    """Фигура примера в сантиметрах. `text` — длина текста автора; 0 — фигура без текста."""
    return ExampleShape(
        shape_id=f"s{xml_id}", kind=ShapeKind.TEXT if text else ShapeKind.SHAPE,
        x=int(x * CM), y=int(y * CM), cx=int(cx * CM), cy=int(cy * CM), z=z,
        xml_id=xml_id, text_len=text,
    )


def zone(text: ExampleShape, role: TypeLevel, *, repeat: int | None = None) -> Zone:
    return Zone(
        zone_id=f"z{text.xml_id}", xml_id=text.xml_id, role=role, repeat=repeat,
        capacity_chars=100, size_pt=12.0, x=text.x, y=text.y, cx=text.cx, cy=text.cy,
    )


def limits(caps: dict[str, int], *, together: int | None = None) -> module.Fits:
    """Подделка замера: текст встаёт в зону, пока не длиннее её лимита.

    `together` — сколько зон встаёт одновременно: больше — не встаёт ни одна
    (так ведёт себя заголовок, уступающий кегль соседям).
    """

    def fits(recipe: Recipe, texts: dict[str, str]) -> dict[str, bool]:
        crowded = together is not None and sum(1 for t in texts.values() if t) > together
        return {
            zone_id: not crowded and len(text) <= caps.get(zone_id, 0)
            for zone_id, text in texts.items()
        }

    return fits


def cards_grid() -> tuple[Recipe, TemplateExample]:
    """Заголовок и три карточки: подложка, полоска под заголовком карточки, два текста.

    Как `ex018` VK Tech: у заголовка карточки своя плашка-полоска. Каталог записал всю
    полосу карточек одним повтором — так, как ошибся на прогоне 28.09.
    """
    title = shape(100, 1, 0.5, 20, 1.5, z=50, text=30)
    shapes = [title]
    zones = [zone(title, TypeLevel.SLIDE_TITLE)]
    for index in range(3):
        left = 1 + index * 7
        card = shape(200 + index * 10, left, 4, 6, 4, z=10 + index * 5)
        strip = shape(201 + index * 10, left + 0.3, 4.3, 5.4, 0.9, z=11 + index * 5)
        head = shape(202 + index * 10, left + 0.3, 4.4, 5.4, 0.7, z=12 + index * 5, text=12)
        body = shape(203 + index * 10, left + 0.3, 5.4, 5.4, 2.2, z=13 + index * 5, text=70)
        shapes += [card, strip, head, body]
        zones += [zone(head, TypeLevel.BODY, repeat=0), zone(body, TypeLevel.CAPTION, repeat=0)]
    recipe = Recipe(
        recipe_id="ex018", example_index=18, kind=RecipeKind.CARDS, zones=zones, repeats=1,
        repeat_xml_ids=[[s.xml_id for s in shapes[1:] if s.xml_id is not None]],
    )
    return recipe, TemplateExample(slide_index=18, shapes=shapes)


CAPS = {"z100": 40, **{f"z{202 + i * 10}": 23 for i in range(3)},
        **{f"z{203 + i * 10}": 160 for i in range(3)}}


def test_a_card_is_found_by_its_plate_not_by_the_catalogue_repeat() -> None:
    """Норма: три карточки — ряд из трёх, заголовок карточки не отрезан своей полоской."""
    recipe, example = cards_grid()

    passport = build_passport(recipe, example, limits(CAPS), slide_area=SLIDE_AREA)

    assert not isinstance(passport, str), passport
    row = passport.rows["r1"]
    assert len(row) == 3
    assert [p.role for p in row[0].places] == [TypeLevel.BODY, TypeLevel.CAPTION]
    assert row[0].decor_xml_ids == [200, 201]


def test_the_slide_title_stays_alone() -> None:
    """Норма: заголовок слайда без подложки — одиночная группа вне ряда."""
    recipe, example = cards_grid()

    passport = build_passport(recipe, example, limits(CAPS), slide_area=SLIDE_AREA)

    assert not isinstance(passport, str)
    first = passport.groups[0]
    assert (first.row, [p.zone_id for p in first.places]) == (None, ["z100"])


def test_a_wider_card_is_not_in_the_row() -> None:
    """Норма: карточка двойной ширины — своя группа, а не четвёртая в ряду (`ex018`)."""
    recipe, example = cards_grid()
    wide = shape(300, 1, 9, 13, 4, z=40)
    head = shape(302, 1.3, 9.4, 5.4, 0.7, z=42, text=12)
    body = shape(303, 1.3, 10.4, 5.4, 2.2, z=43, text=70)
    example = example.model_copy(update={"shapes": [*example.shapes, wide, head, body]})
    recipe = recipe.model_copy(update={"zones": [
        *recipe.zones, zone(head, TypeLevel.BODY), zone(body, TypeLevel.CAPTION)
    ]})

    passport = build_passport(
        recipe, example, limits(CAPS | {"z302": 23, "z303": 160}), slide_area=SLIDE_AREA
    )

    assert not isinstance(passport, str), passport
    assert len(passport.rows["r1"]) == 3
    assert next(g for g in passport.groups if 300 in g.decor_xml_ids).row is None


def test_cards_without_a_plate_take_the_catalogue_repeats() -> None:
    """Норма: подложек нет — карточки берутся по повторам каталога."""
    title = shape(100, 1, 0.5, 20, 1.5, z=1, text=30)
    texts = [shape(200 + i, 1 + i * 7, 4, 6, 3, z=2 + i, text=80) for i in range(3)]
    lines = [shape(300 + i, 1 + i * 7, 3.8, 6, 0.1, z=5 + i) for i in range(3)]
    recipe = Recipe(
        recipe_id="ex005", example_index=5, kind=RecipeKind.CARDS, repeats=3,
        zones=[zone(title, TypeLevel.SLIDE_TITLE),
               *(zone(t, TypeLevel.BODY, repeat=i) for i, t in enumerate(texts))],
        repeat_xml_ids=[[200 + i, 300 + i] for i in range(3)],
    )
    example = TemplateExample(slide_index=5, shapes=[title, *texts, *lines])
    caps = {"z100": 40, **{f"z{200 + i}": 120 for i in range(3)}}

    passport = build_passport(recipe, example, limits(caps), slide_area=SLIDE_AREA)

    assert not isinstance(passport, str), passport
    assert [g.decor_xml_ids for g in passport.rows["r1"]] == [[300], [301], [302]]


def test_a_place_short_of_two_words_holds_a_number() -> None:
    """Норма: «01» в карточке — место под число, а не отказ всему примеру."""
    recipe, example = cards_grid()
    caps = CAPS | {f"z{202 + i * 10}": 3 for i in range(3)}

    passport = build_passport(recipe, example, limits(caps), slide_area=SLIDE_AREA)

    assert not isinstance(passport, str), passport
    head = passport.rows["r1"][0].places[0]
    assert (head.kind, head.capacity_chars) == (PlaceKind.NUMBER, len(sample_number(3)))


def test_a_place_that_holds_nothing_is_named() -> None:
    """Нарушитель: зона не держит и знака — паспорта нет, причина названа."""
    recipe, example = cards_grid()

    made = build_passport(recipe, example, limits(CAPS | {"z212": 0}), slide_area=SLIDE_AREA)

    assert made == "зона z212 не держит и одного знака кеглем автора"


def test_the_trial_fill_rejects_places_that_do_not_land_together() -> None:
    """Нарушитель: по одному места встают, все вместе — нет (пробная заливка)."""
    recipe, example = cards_grid()

    made = build_passport(recipe, example, limits(CAPS, together=3), slide_area=SLIDE_AREA)

    assert isinstance(made, str) and made.startswith("пробная заливка: не встали зоны")


def test_capacity_is_the_longest_text_that_lands() -> None:
    """Норма: ёмкость — длина самого длинного пробного текста, который встал."""
    recipe, _ = cards_grid()
    body = next(z for z in recipe.zones if z.zone_id == "z203")

    assert capacity(recipe, body, limits({"z203": 90}), ceiling=400) == len(sample(90))


def test_the_catalogue_gets_passports_and_names_the_rest() -> None:
    """Норма: каталог — у кого паспорт, у кого причина; рецепт проходит свои валидаторы."""
    recipe, example = cards_grid()
    broken = recipe.model_copy(update={"recipe_id": "ex019", "example_index": 19})
    grid = SimpleNamespace(width_emu=12_000_000, height_emu=6_750_000)
    ds = DesignSystem.model_construct(recipes=[recipe, broken], grid=grid)
    manifest = type("M", (), {"examples": [example]})()

    ds2, report = with_passports(ds, manifest, fits=limits(CAPS))  # type: ignore[arg-type]

    assert report.with_passport == ["ex018"]
    assert report.rejected == {"ex019": "примера №19 нет в манифесте"}
    assert ds2.recipes[0].passport is not None and ds2.recipes[1].passport is None


@pytest.mark.parametrize("chars", [0, 5, 40, 400])
def test_the_sample_never_exceeds_its_length(chars: int) -> None:
    """Норма: пробный текст и пробное число не длиннее заказанного."""
    assert len(sample(chars)) <= chars
    assert len(sample_number(chars)) <= chars
