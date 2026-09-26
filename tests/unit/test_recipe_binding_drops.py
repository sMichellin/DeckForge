"""Блок, которому не досталось зоны, называется. Change `a-zone-less-block-is-not-dropped`,
таск RG28 (`docs/agents/tasks-25-09.md`).

Прогон 25.09 на `b937ec5` починил читаемость — разорванных слов ноль, текста за краем
ноль — и открыл то, что было ею заслонено: **семь слайдов из тридцати несли только
заголовок**. WorkSpace s01, s04, s05, s10 и VK Tech s04, s08, s10. Факты, которые план
передал слайду, исчезали между композицией и записью, и узнать о них можно было только
по находке аудита постфактум.

Причин оказалось три, и здесь проверяются все:

1. рецепт с одной заголовочной зоной законно доставался слайду с фактами — мест
   в отборе никто не считал (`recipe_picker`);
2. блок, которому зоны не нашлось, снимался молча (`bind_to_recipe`);
3. текст резался по `capacity_chars` до того, как его увидит вписывание, — и терялось
   то, что встало бы (RG29).

Каталог синтетический: проверяется правило, а не конкретный шаблон. Замер на шаблонах
кейса идёт живым прогоном.
"""

from __future__ import annotations

from deckforge.composition.recipe_binding import bind_to_recipe, body_seats
from deckforge.composition.recipe_picker import pick_recipe
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import CalloutTone, ImageSource, SlideIntent, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    CalloutBlock,
    ImageBlock,
    KpiBlock,
    KpiItem,
    QuoteBlock,
    SlideIR,
    TextBlock,
)

HEADLINE = "Правки занимают минуты, а не дни"
FACT = "Пайплайн разбирает шаблон и достаёт из него дизайн-систему целиком"


def zone(
    zone_id: str,
    role: TypeLevel,
    *,
    repeat: int | None = None,
    chars: int = 80,
    framed: bool = False,
) -> Zone:
    """Зона рецепта. `framed` — с рамкой: такую меряет вписывание, а не счёт знаков."""
    frame = {"x": 0, "y": 0, "cx": 5_000_000, "cy": 1_000_000} if framed else {}
    return Zone(
        zone_id=zone_id,
        xml_id=int(zone_id[1:]),
        role=role,
        repeat=repeat,
        capacity_chars=chars,
        **frame,  # type: ignore[arg-type]
    )


def recipe(
    index: int, kind: RecipeKind = RecipeKind.TEXT, *, repeats: int = 0,
    zones: list[Zone] | None = None,
) -> Recipe:
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=kind,
        repeats=repeats,
        zones=zones or [zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)],
    )


def plan(**kwargs: object) -> SlidePlan:
    data: dict[str, object] = {
        "slide_id": "s01",
        "intent": SlideIntent.EVIDENCE,
        "headline": HEADLINE,
        "fact_refs": ["f1", "f2", "f3"],
    }
    data.update(kwargs)
    return SlidePlan(**data)  # type: ignore[arg-type]


def slide_ir(blocks: list[object]) -> SlideIR:
    return SlideIR(
        slide_id="s01", layout_id="L07", variant="A", blocks=blocks  # type: ignore[arg-type]
    )


def body(count: int) -> list[object]:
    """Заголовок и `count` блоков тела — то, что пишет композитор на слайд с фактами."""
    blocks: list[object] = [TextBlock(block_id="t", role=TextRole.TITLE, text=HEADLINE)]
    blocks += [
        TextBlock(block_id=f"b{index}", role=TextRole.BODY, text=f"{FACT} {index}")
        for index in range(count)
    ]
    return blocks


# --- 1. снятый блок называется ---------------------------------------------------


def test_a_block_left_without_a_zone_is_named_in_the_notes() -> None:
    """Нарушитель: мест под тело одно, блоков тела три — два снимаются.

    До правки они уходили молча: докстринг признавал снятие, отчёт о нём не знал.
    """
    notes: list[str] = []
    narrow = recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)])

    bound = bind_to_recipe(slide_ir(body(3)), narrow, notes)

    dropped = [note for note in notes if "снят" in note]
    assert len(dropped) == 2, notes
    assert all("s01" in note and "ex001" in note for note in dropped)
    # Число мест и число блоков названы: по заметке видно, чего не хватило.
    assert all("мест под тело 1" in note and "блоков тела 3" in note for note in dropped)
    assert [block.block_id for block in bound.blocks] == ["t", "b0"]


def test_a_recipe_with_room_for_everything_says_nothing() -> None:
    """Норма: мест хватило — про снятие в заметках ни строки."""
    notes: list[str] = []
    roomy = recipe(
        1,
        zones=[
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z2", TypeLevel.BODY_LARGE),
            zone("z3", TypeLevel.BODY),
            zone("z4", TypeLevel.CAPTION),
        ],
    )

    bound = bind_to_recipe(slide_ir(body(3)), roomy, notes)

    assert not [note for note in notes if "снят" in note]
    assert len(bound.blocks) == 4


def test_the_title_is_never_dropped() -> None:
    """Заголовок остаётся всегда: зона ему ищется по всем зонам, а не по свободным."""
    notes: list[str] = []
    one = recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE)])

    bound = bind_to_recipe(slide_ir(body(2)), one, notes)

    assert [block.block_id for block in bound.blocks] == ["t"]
    assert len([note for note in notes if "снят" in note]) == 2


def test_bullets_that_outnumber_the_repeats_are_named() -> None:
    """Нарушитель: пунктов пять, повторов три — два последних сняты и названы.

    `zip(strict=False)` обрывал хвост молча; это и есть `integrity.content_lost`
    на слайдах-рядах.
    """
    notes: list[str] = []
    row = recipe(
        2,
        repeats=3,
        zones=[zone("z1", TypeLevel.SLIDE_TITLE)]
        + [zone(f"z{index + 2}", TypeLevel.BODY, repeat=index) for index in range(3)],
    )
    bullets = BulletsBlock(
        block_id="b",
        items=[BulletItem(text=f"{FACT} {index}") for index in range(5)],
    )

    bind_to_recipe(slide_ir([*body(0), bullets]), row, notes)

    assert any("повторов" in note and "пунктов 5" in note for note in notes), notes


def test_a_paragraph_takes_a_card_when_free_zones_run_out() -> None:
    """Абзац встаёт в карточку ряда, если свободных зон не осталось.

    Прогон RG28 на VK Education: «блок b02 снят — мест под тело 4, блоков тела 2».
    Противоречие настоящее — четыре места были повторами, а в повтор до этой правки
    мог встать только список. Пустая карточка рядом со снятым абзацем хуже карточки
    с абзацем.
    """
    notes: list[str] = []
    row = recipe(
        3,
        repeats=3,
        zones=[zone("z1", TypeLevel.SLIDE_TITLE)]
        + [zone(f"z{index + 2}", TypeLevel.BODY, repeat=index) for index in range(3)],
    )

    bound = bind_to_recipe(slide_ir(body(2)), row, notes)

    assert len(bound.blocks) == 3, [block.block_id for block in bound.blocks]
    assert not [note for note in notes if "снят" in note], notes


def test_a_wordless_block_is_named_not_swallowed() -> None:
    """Нарушитель: блок без единого слова. Зона — текстовая фигура, ставить нечего.

    Показатель сюда больше не входит: решение изменено в RG48
    (`a-diagram-becomes-text-rather-than-nothing`). У показателя и схемы слова есть —
    значение с подписью и шаги, — и зона их принимает, теряя оформление. Прогон 26.09
    показал цену прежнего решения: схема дважды оказывалась единственным содержанием
    слайда, и снятие оставляло заголовок на пустом поле.

    У картинки слов нет, и для неё правило прежнее.
    """
    notes: list[str] = []
    picture = ImageBlock(block_id="p", source=ImageSource.ASSET, asset_ref="a1")

    bind_to_recipe(slide_ir([*body(0), picture]), recipe(1), notes)

    assert any('блок p («image»)' in note and "снят" in note for note in notes), notes


def test_a_metric_now_keeps_its_words() -> None:
    """Обратная сторона того же решения: показатель отдаёт зоне значение и подпись."""
    notes: list[str] = []
    kpi = KpiBlock(block_id="k", items=[KpiItem(value="30%", label="доля")])

    bound = bind_to_recipe(slide_ir([*body(0), kpi]), recipe(1), notes)

    placed = [block for block in bound.blocks if block.block_id == "k"]
    assert placed, "показатель снят, хотя слова в нём есть"
    assert "30%" in placed[0].text and "доля" in placed[0].text  # type: ignore[union-attr]


def test_a_quote_goes_into_a_zone_as_plain_text() -> None:
    """Цитата и callout больше не пропадают целиком: текст встаёт в зону, оформление — нет.

    Терять полосу хуже, чем оставить её, но лучше, чем терять слова: до правки
    `_lines` возвращал для них пусто, и блок уходил со слайда молча.
    """
    notes: list[str] = []
    quote = QuoteBlock(block_id="q", text=FACT)
    callout = CalloutBlock(block_id="c", text=FACT, tone=CalloutTone.INSIGHT)
    roomy = recipe(
        1,
        zones=[
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z2", TypeLevel.BODY),
            zone("z3", TypeLevel.BODY),
        ],
    )

    bound = bind_to_recipe(slide_ir([*body(0), quote, callout]), roomy, notes)

    assert [block.block_id for block in bound.blocks] == ["t", "q", "c"]
    assert all(isinstance(block, TextBlock) for block in bound.blocks)
    assert len([note for note in notes if "простым текстом" in note]) == 2, notes


# --- 2. места участвуют в отборе --------------------------------------------------


def test_body_seats_counts_free_zones_and_repeats() -> None:
    """Счёт мест: свободные зоны и повторы с зонами, без зоны заголовка."""
    assert body_seats(recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE)])) == 0
    assert body_seats(recipe(1)) == 1
    row = recipe(
        2,
        repeats=2,
        zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY, repeat=0),
               zone("z3", TypeLevel.BODY, repeat=1), zone("z4", TypeLevel.CAPTION)],
    )
    assert body_seats(row) == 3


def test_a_recipe_without_room_is_not_picked_when_another_has_it() -> None:
    """Нарушитель отбора: у рецепта одно место, у слайда три факта — берётся второй.

    До правки `_fits` спрашивал про знаки и повторы, но не про места, и слайд
    получал рецепт, на который влезает один факт из трёх.
    """
    cramped = recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)])
    roomy = recipe(
        2,
        zones=[zone("z1", TypeLevel.SLIDE_TITLE)]
        + [zone(f"z{index + 2}", TypeLevel.BODY) for index in range(3)],
    )

    chosen = pick_recipe(plan(), [cramped, roomy])

    assert chosen is not None and chosen.recipe_id == "ex002"


def test_a_recipe_without_a_single_seat_is_rejected() -> None:
    """Нарушитель отбора, от которого и пустели слайды: у рецепта одна зона — заголовок.

    Тело такого слайда снимается целиком, и остаётся заголовок на чёрном поле. Отказ
    здесь жёсткий, в отличие от нехватки: нехватка мест — потеря части содержания,
    ноль мест — потеря всего.
    """
    blind = recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE)])
    plain = recipe(2, zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)])

    chosen = pick_recipe(plan(), [blind, plain])

    assert chosen is not None and chosen.recipe_id == "ex002"


def test_a_recipe_short_of_seats_is_still_usable_just_second() -> None:
    """Норма: мест меньше, чем фактов, — но рецепт не отвергнут.

    Нехватка мест не равна потере содержания: список из трёх пунктов на одном
    свободном месте встаёт одним абзацем, и текст цел. Отвергать такой рецепт значило
    бы ради формы уводить слайд на пустой макет.
    """
    only = recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)])

    chosen = pick_recipe(plan(), [only])

    assert chosen is not None and chosen.recipe_id == "ex001"


def test_when_no_recipe_has_room_the_shortfall_is_named() -> None:
    """Мест не хватает никому — берётся наибольший, и это названо.

    Отката в «нет рецепта» быть не должно: слайд на пустом макете хуже слайда,
    с которого снят один факт.
    """
    notes: list[str] = []
    one = recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)])
    two = recipe(
        2,
        zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY),
               zone("z3", TypeLevel.BODY)],
    )

    chosen = pick_recipe(plan(), [one, two], notes=notes)

    assert chosen is not None and chosen.recipe_id == "ex002"
    assert any("часть содержания на слайд не встанет" in note for note in notes), notes


def test_a_structural_slide_keeps_a_title_only_recipe() -> None:
    """Норма: обложке без места под тело рецепт всё равно достаётся.

    Одна крупная фраза — её законная композиция, и отказ увёл бы титульный слайд
    с его вида: из 13 рецептов VK Education без единого места 8 — обложки.
    """
    cover = recipe(1, RecipeKind.COVER, zones=[zone("z1", TypeLevel.DISPLAY)])

    chosen = pick_recipe(plan(intent=SlideIntent.TITLE, fact_refs=["f1"]), [cover])

    assert chosen is not None and chosen.recipe_id == "ex001"


def test_a_cover_with_a_subtitle_wins_over_one_without() -> None:
    """Обложке нужно одно место — под подзаголовок, и рецепт с ним идёт первым.

    Прогон RG28 показал обратное: обложке WorkSpace достался рецепт без единого места,
    подзаголовок сняли, и слайд уехал в файл заголовком на чёрном поле. Место по числу
    фактов структурному слайду не нужно, а одно — нужно.
    """
    bare = recipe(1, RecipeKind.COVER, zones=[zone("z1", TypeLevel.DISPLAY)])
    with_sub = recipe(
        2,
        RecipeKind.COVER,
        zones=[zone("z1", TypeLevel.DISPLAY), zone("z2", TypeLevel.SECTION_SUBTITLE)],
    )

    chosen = pick_recipe(plan(intent=SlideIntent.TITLE, fact_refs=["f1"]), [bare, with_sub])

    assert chosen is not None and chosen.recipe_id == "ex002"


def test_a_cover_is_not_rejected_for_facts_it_will_never_print() -> None:
    """Обложка меряется по заголовку, а не по фактам плана.

    У VK WorkSpace одна обложка (вместимость 32) и один разделитель (вместимость 0).
    Обложку отвергала проверка знаков RG23 — 32 против половины всех фактов слайда, —
    а разделитель проходил: вместимость ноль означает «посчитать не удалось», и условие
    молчит. Титульный слайд получал разделитель вместо обложки шаблона.
    """
    cover = recipe(
        1, RecipeKind.COVER, zones=[zone("z1", TypeLevel.DISPLAY, chars=32)]
    )
    divider = recipe(2, RecipeKind.SECTION, zones=[zone("z1", TypeLevel.DISPLAY, chars=0)])

    chosen = pick_recipe(
        plan(intent=SlideIntent.TITLE, headline="AI-генерация презентаций"),
        [cover, divider],
        needs_chars=400,
    )

    assert chosen is not None and chosen.recipe_id == "ex001"


# --- 3. обрезка не опережает вписывание -------------------------------------------


def test_a_framed_zone_is_left_to_the_fitting() -> None:
    """Нарушитель: зона с рамкой и текст длиннее `capacity_chars` — текст цел.

    Рамку меряет вписывание (RG29): оно знает настоящую ширину слова и спускает
    кегль по лестнице. `capacity_chars` — оценка по знакам при исходном кегле,
    и она всегда строже. В прогоне 25.09 от блока осталось 25 знаков из 64.
    """
    notes: list[str] = []
    framed = recipe(
        1,
        zones=[zone("z1", TypeLevel.SLIDE_TITLE, framed=True),
               zone("z2", TypeLevel.BODY, chars=25, framed=True)],
    )

    # Текста 64 знака при вместимости 25: по знакам он был бы обрезан втрое, а рамку
    # меряет вписывание — оно и решает, спускать кегль или сокращать.
    bound = bind_to_recipe(slide_ir(body(1)), framed, notes)

    assert bound.blocks[1].text == f"{FACT} 0"  # type: ignore[union-attr]
    assert not [note for note in notes if "обрезан" in note]


def test_a_zone_that_holds_no_line_is_not_a_seat() -> None:
    """Зона с измеренной рамкой и нулевой вместимостью — не место.

    У VK Tech зона высотой 0,46 см оставляет 0,2 см полезной высоты: ноль строк
    двенадцатым кеглем. Текст в ней уезжает выше рамки — три находки читаемости
    прогона 25.09. А зона без кегля — это незнание, а не факт, и её мы не отсеиваем.
    """
    measured = zone("z2", TypeLevel.BODY, chars=0, framed=True)
    measured = measured.model_copy(update={"size_pt": 12.0})
    unknown = zone("z3", TypeLevel.BODY, chars=0, framed=True)

    dead = recipe(1, zones=[zone("z1", TypeLevel.SLIDE_TITLE, framed=True), measured])
    blind = recipe(2, zones=[zone("z1", TypeLevel.SLIDE_TITLE, framed=True), unknown])

    assert body_seats(dead) == 0
    assert body_seats(blind) == 1


def test_a_zone_without_a_frame_is_still_clipped() -> None:
    """Норма: рамки нет — мерить вписыванию нечего, и знаки остаются единственной защитой."""
    notes: list[str] = []
    blind = recipe(
        1, zones=[zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY, chars=25)]
    )

    bound = bind_to_recipe(slide_ir(body(1)), blind, notes)

    assert len(bound.blocks[1].text) <= 25  # type: ignore[union-attr]
