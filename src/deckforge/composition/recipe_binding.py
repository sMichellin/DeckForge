"""Текст колоды по зонам композиции. Change `compose-by-the-recipe`, таск 05b.

Модель пишет содержание, как писала: заголовок, пункты, абзац. Разложить их по зонам
шаблона — счёт, а не решение модели: зоны различаются номером повтора и ступенью
лестницы, и это те же числа, что уже посчитал каталог композиций.

Пункт списка становится отдельным блоком на свой повтор: у шаблона ряд из трёх карточек,
а не один список на три строки, и вёрстка кладёт в каждую карточку свой текст.

Блок получает зону своей ступени (change `a-block-goes-to-a-zone-of-its-level`, RG30):
соответствие роли блока и ступени зоны задано таблицей `ROLE_LEVELS`. Раньше свободные
зоны раздавались по порядку блоков от крупной ступени к мелкой, и первый же блок тела
забирал зону разделителя — вывод слайда вставал мелкой строкой над пояснением кеглем
обложки.
"""

from __future__ import annotations

from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import (
    Block,
    BulletsBlock,
    CalloutBlock,
    QuoteBlock,
    SlideIR,
    TextBlock,
)

#: Доля текста, ниже которой обрезка перестаёт быть сокращением. От предложения,
#: от которого осталось меньше половины, автора уже не остаётся: на холодном шаблоне
#: зоны вмещали по два знака, и по слайду разъехались одиночные буквы (прогон
#: `cb04bb47fc47`). Одна доля на оба условия отбора — заголовок и содержание целиком.
#: Жила в `recipe_picker`, пока отбор не начал спрашивать у раскладки число мест:
#: зависимость развёрнута, счёт зон стоит ниже выбора рецепта, а не наоборот.
KEEP_SHARE = 0.5

#: Ступени, которые несут заголовок внутри повтора: у карточки это её название.
#: Заголовка слайда здесь нет: он один на слайд и повтору не принадлежит, даже если
#: каталог отнёс его рамку к ряду.
CARD_TITLES = (TypeLevel.CARD_TITLE, TypeLevel.SECTION_SUBTITLE)

#: Роль блока → ступени зоны, по порядку предпочтения. Таблица, а не порядок перечисления
#: `TypeLevel`: соответствие обязано быть видно и проверяемо — тот же приём, что
#: `recipe_picker.RELATED_KINDS`. Все ступени строки — свои: тело в `body_large` стоит
#: законно и заметки не даёт. Чужая ступень берётся, только когда своих в рецепте нет.
ROLE_LEVELS: dict[TextRole, tuple[TypeLevel, ...]] = {
    TextRole.TITLE: (TypeLevel.SLIDE_TITLE, TypeLevel.DISPLAY),
    TextRole.SUBTITLE: (TypeLevel.SECTION_SUBTITLE, TypeLevel.BODY_LARGE),
    TextRole.BODY: (TypeLevel.BODY_LARGE, TypeLevel.BODY, TypeLevel.CARD_TITLE),
    TextRole.CAPTION: (TypeLevel.CAPTION, TypeLevel.LABEL),
}

#: На обложке заголовок законно набран кеглем `display`: там это и есть заголовок.
#: Исключение задаётся видом рецепта, а не размером зоны.
COVER_TITLE_LEVELS = (TypeLevel.DISPLAY, TypeLevel.SLIDE_TITLE)

_LADDER = list(TypeLevel)


def _levels(role: TextRole, recipe: Recipe) -> tuple[TypeLevel, ...]:
    """Свои ступени роли на этом рецепте."""
    if role is TextRole.TITLE and recipe.kind is RecipeKind.COVER:
        return COVER_TITLE_LEVELS
    return ROLE_LEVELS[role]


def _size(zone: Zone) -> tuple[int, str]:
    """Размер зоны для выбора внутри ступени: площадь рамки, нет рамки — вместимость."""
    if zone.cx is not None and zone.cy is not None:
        return zone.cx * zone.cy, zone.zone_id
    return zone.capacity_chars, zone.zone_id


def _own_zone(zones: list[Zone], levels: tuple[TypeLevel, ...]) -> Zone | None:
    """Зона своей ступени — первой по предпочтению, внутри ступени самая большая."""
    for level in levels:
        same = [zone for zone in zones if zone.role is level]
        if same:
            return max(same, key=_size)
    return None


def _nearest_zone(zones: list[Zone], levels: tuple[TypeLevel, ...]) -> Zone | None:
    """Зона чужой ступени, ближайшей к своим; при равенстве — ниже своей, а не выше.

    Ниже — потому что так сохраняется лестница: тело мельче заголовка лучше тела кеглем
    обложки. Выше берётся, только когда ниже нет ничего такого же близкого.
    """
    if not zones:
        return None
    own = [_LADDER.index(level) for level in levels]

    def distance(zone: Zone) -> tuple[int, bool, int, str]:
        index = _LADDER.index(zone.role)
        area, zone_id = _size(zone)
        return min(abs(index - mine) for mine in own), index < min(own), -area, zone_id

    return min(zones, key=distance)


def _role_of(block: Block) -> TextRole:
    role = getattr(block, "role", None)
    return role if isinstance(role, TextRole) else TextRole.BODY


def _title_zone(recipe: Recipe) -> Zone | None:
    """Зона заголовка слайда — по всем зонам, не только свободным.

    Ищем везде, потому что заголовок обязан получить заголовок: зона заголовка, попавшая
    в повтор, — это ошибка замера, и платить за неё пунктом списка в шапке слайда нельзя.
    Ступени — по `ROLE_LEVELS` с исключением обложки; внутри ступени — самый крупный кегль.
    """
    for level in _levels(TextRole.TITLE, recipe):
        titles = [zone for zone in recipe.zones if zone.role is level]
        if titles:
            return max(titles, key=lambda zone: (zone.size_pt or 0, zone.zone_id))
    return None


def _usable(zone: Zone) -> bool:
    """Зона, в которую есть смысл писать.

    Вместимость ноль значит одно из двух. Посчитать не удалось — у фигуры примера нет
    кегля (`size_pt` пуст) или нет рамки; это незнание, и зона остаётся кандидатом:
    отсеять её из-за собственной слепоты хуже, чем попробовать.

    Или рамка измерена и не держит ни строки. Это уже факт, а не незнание: у VK Tech
    зона высотой 0,46 см при отступах текстового поля оставляет 0,2 см полезной
    высоты — ноль строк двенадцатым кеглем. Текст в такой зоне уезжает выше рамки,
    и три находки читаемости прогона 25.09 — ровно она. Местом она не считается.
    """
    return zone.capacity_chars > 0 or zone.size_pt is None or not zone.has_frame


def _zones_of_repeat(recipe: Recipe, index: int, *, skip: Zone | None = None) -> list[Zone]:
    """Зоны одного повтора, от заголовка карточки к её тексту."""
    same = [
        zone
        for zone in recipe.zones
        if zone.repeat == index and zone is not skip and _usable(zone)
    ]
    return sorted(same, key=lambda zone: (zone.role not in CARD_TITLES, zone.zone_id))


def _free_zones(recipe: Recipe) -> list[Zone]:
    """Зоны вне повторов, куда есть смысл писать. Порядок им не нужен: зону под блок
    выбирает `_zone_for`."""
    return [zone for zone in recipe.zones if zone.repeat is None and _usable(zone)]


def body_seats(recipe: Recipe) -> int:
    """Сколько блоков тела рецепт способен принять: свободные зоны и повторы с зонами.

    Тот же счёт, которым раскладывает `bind_to_recipe`, вынесенный наружу: зона
    заголовка из него исключена — она достаётся заголовку слайда, а не телу.

    Нужен отбору (`recipe_picker`). До RG28 отбор считал знаки (RG23) и повторы,
    но не места: рецепт с единственной заголовочной зоной законно доставался слайду
    с тремя фактами, и все три уходили в ничто. На шаблонах кейса таких рецептов
    4 из 29 (VK WorkSpace) и 13 из 45 (VK Education).
    """
    heading = _title_zone(recipe)
    free = [zone for zone in _free_zones(recipe) if zone is not heading]
    return len(free) + len(_buckets(recipe, heading))


def _zone_for(
    block: Block,
    zones: list[Zone],
    recipe: Recipe,
    slide: SlideIR,
    notes: list[str] | None,
) -> Zone | None:
    """Свободная зона под блок: своей ступени, а нет её — ближайшей, с заметкой."""
    role = _role_of(block)
    levels = _levels(role, recipe)
    zone = _own_zone(zones, levels)
    if zone is not None:
        return zone
    zone = _nearest_zone(zones, levels)
    if zone is not None and notes is not None:
        notes.append(
            f"слайд {slide.slide_id}: блок {block.block_id} ({role.value}) — зоны своей "
            f"ступени ({', '.join(level.value for level in levels)}) в рецепте "
            f"{recipe.recipe_id} нет, взята {zone.zone_id} ({zone.role.value})"
        )
    return zone


def _buckets(recipe: Recipe, heading: Zone | None) -> list[tuple[int, list[Zone]]]:
    """Повторы, которым есть куда писать: номер повтора и его зоны.

    Повтор без своих зон пропускается, а не обрывает раскладку: иначе один пустой повтор
    в середине ряда съедал бы все оставшиеся пункты списка.
    """
    numbered = (
        (index, _zones_of_repeat(recipe, index, skip=heading)) for index in range(recipe.repeats)
    )
    return [(index, zones) for index, zones in numbered if zones]


def _lines(block: Block) -> list[str]:
    """Строки блока. Пусто — текста в блоке нет, и зона его принять не может.

    Цитата и callout сюда входят: зона — текстовая фигура, и поставить в неё их текст
    можно, потеряв полосу и плашку. Терять оформление хуже, чем ничего, но лучше,
    чем терять слова: до RG28 такой блок уходил со слайда целиком и молча.
    """
    if isinstance(block, BulletsBlock):
        return [item.text for item in block.items if item.text.strip()]
    if isinstance(block, TextBlock | QuoteBlock | CalloutBlock):
        return [line for line in block.text.splitlines() if line.strip()]
    return []


def _clip(text: str, zone: Zone) -> str:
    """Обрезать по словам до вместимости зоны, оставив запас под вписывание.

    У зоны с рамкой текст меряет вписывание (RG29): оно знает настоящую ширину слова
    в этой гарнитуре и спускает кегль по лестнице шаблона. `capacity_chars` — оценка
    по знакам при **исходном** кегле, и для зоны с рамкой она всегда строже, чем надо.
    Резать по ней до вписывания значит терять то, что встало бы: в прогоне 25.09
    от блока осталось 25 знаков из 64 в зоне, которая держала весь текст.

    Но и не резать вовсе нельзя. Прогон с полностью снятой обрезкой дал вдвое больше
    находок читаемости: текст, который вписыванию не по силам, уезжает в файл кеглем
    ниже порога или выше рамки. Вписывание отыгрывает примерно ступень-две лестницы,
    то есть около двойной вместимости (`KEEP_SHARE` — та же доля, с другой стороны),
    и дальше рамка кончается.

    Рамки нет — вписыванию не за что взяться, и знаки остаются единственной защитой.
    Вместимость ноль — её не удалось посчитать, и тогда не режем: своё незнание
    дороже чужого текста.
    """
    limit = zone.capacity_chars
    if zone.has_frame:
        limit = int(limit / KEEP_SHARE)
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(" ,;:—-")


def _note_clip(notes: list[str] | None, slide: SlideIR, block: TextBlock, before: str) -> None:
    """Назвать обрезку, от которой осталось меньше половины текста.

    Отбор рецептов (RG23) делает такие случаи редкими, но не невозможными: модель пишет
    длиннее, чем обещала. Молчаливая обрезка — это подмена содержания, о которой никто
    не узнает: на холодном шаблоне так уехали в колоду одиночные буквы.
    """
    if notes is None or len(block.text) >= len(before) * KEEP_SHARE:
        return
    notes.append(
        f"слайд {slide.slide_id}: блок {block.block_id} обрезан до вместимости зоны "
        f"{block.zone_id} — было {len(before)} знаков, осталось {len(block.text)}"
    )


def _note_drop(
    notes: list[str] | None,
    slide: SlideIR,
    block: Block,
    recipe: Recipe,
    seats: int,
    wanted: int,
) -> None:
    """Назвать блок, которому зоны не досталось.

    Поведение прежнее — блок снимается, рисовать его некуда, — но молчание превращало
    решение в пропажу: факт исчезал между композицией и записью, и узнать о нём можно
    было только по находке аудита постфактум.
    """
    if notes is None:
        return
    notes.append(
        f"слайд {slide.slide_id}: блок {block.block_id} снят — свободной зоны "
        f"в рецепте {recipe.recipe_id} не осталось (мест под тело {seats}, "
        f"блоков тела {wanted})"
    )


def _note_wordless(
    notes: list[str] | None, slide: SlideIR, block: Block, recipe: Recipe
) -> None:
    """Назвать блок, у которого нет текста: показатель, схему, таблицу, картинку.

    Зона рецепта — текстовая фигура автора, и поставить в неё показатель нечем.
    Ставить такие блоки в зоны — отдельная работа с отдельным замером; пока они
    снимаются, но больше не молча.
    """
    if notes is None or isinstance(block, TextBlock | BulletsBlock):
        return
    notes.append(
        f"слайд {slide.slide_id}: блок {block.block_id} («{block.type}») снят — "
        f"рецепт {recipe.recipe_id} ставит в зоны только текст"
    )


def _note_plain(
    notes: list[str] | None, slide: SlideIR, block: Block, recipe: Recipe
) -> None:
    """Назвать цитату или callout, поставленные в зону простым текстом."""
    if notes is None or not isinstance(block, QuoteBlock | CalloutBlock):
        return
    notes.append(
        f"слайд {slide.slide_id}: блок {block.block_id} («{block.type}») поставлен "
        f"в зону рецепта {recipe.recipe_id} простым текстом — полосу и плашку "
        "зона не несёт"
    )


def _note_lost_lines(
    notes: list[str] | None,
    slide: SlideIR,
    block: Block,
    recipe: Recipe,
    placed: int,
    total: int,
) -> None:
    """Назвать пункты списка, которым не хватило повторов."""
    if notes is None:
        return
    notes.append(
        f"слайд {slide.slide_id}: блок {block.block_id} — повторов в рецепте "
        f"{recipe.recipe_id} {placed}, пунктов {total}; последние {total - placed} сняты"
    )


def _in_zone(
    block: Block, zone: Zone, text: str, index: int, role: TextRole | None = None
) -> TextBlock:
    """Блок, стоящий в зоне шаблона: без координат и плейсхолдера — рамку дал автор.

    Роль — переданная (заголовок в зоне `display` обложки остаётся заголовком); не передана —
    по ступени зоны, как раньше: так раскладываются пункты по повторам.
    """
    if role is None:
        role = TextRole.TITLE if zone.role is TypeLevel.SLIDE_TITLE else TextRole.BODY
    return TextBlock(
        block_id=f"{block.block_id}-{index}" if index else block.block_id,
        role=role,
        text=_clip(text, zone),
        zone_id=zone.zone_id,
    )


def _placed(
    block: Block,
    zone: Zone,
    text: str,
    index: int,
    slide: SlideIR,
    notes: list[str] | None,
    role: TextRole | None = None,
) -> TextBlock:
    """Блок в зоне, с оговоркой, если от текста осталось меньше половины."""
    placed = _in_zone(block, zone, text, index, role)
    _note_clip(notes, slide, placed, text)
    return placed


def bind_to_recipe(slide: SlideIR, recipe: Recipe, notes: list[str] | None = None) -> SlideIR:
    """Разложить текст слайда по зонам композиции.

    Заголовок идёт в зону заголовка, пункты — по одному на повтор, остальной текст —
    в свободную зону своей ступени (`ROLE_LEVELS`, RG30). Блок, которому зоны не досталось,
    из слайда уходит: вёрстка его всё равно не нарисует, а в отчёте он выглядел бы как
    поставленный. **Но уходит он теперь названным** (RG28): молчаливое снятие превращало
    решение в пропажу, и по прогону 25.09 семь слайдов из тридцати несли один заголовок,
    а по отчёту это было видно только счётом находок аудита.

    `notes` получает: обрезку, от которой осталось меньше половины текста (RG23); блок,
    вставший в зону чужой ступени (RG30); снятый блок и причину — зон не осталось,
    текста в блоке нет, повторов меньше, чем пунктов (RG28).
    """
    heading = _title_zone(recipe)
    title_zone = heading
    rest = [zone for zone in _free_zones(recipe) if zone is not heading]
    buckets = _buckets(recipe, heading)
    seats = body_seats(recipe)
    wanted = sum(1 for block in slide.blocks if _role_of(block) is not TextRole.TITLE)

    blocks: list[Block] = []
    used_repeat = 0

    def take_repeat() -> tuple[int, Zone] | None:
        """Следующий свободный повтор — абзацу, когда свободных зон не осталось.

        Повтор — это карточка ряда, и абзац в ней стоит законно: модель написала два
        абзаца там, где шаблон ждал список, и до этой правки второй абзац снимался
        при четырёх пустых карточках рядом. По заметке прогона это выглядело прямым
        враньём: «мест под тело 4, блоков тела 2» — и блок снят.
        """
        nonlocal used_repeat
        if used_repeat >= len(buckets):
            return None
        index, zones = buckets[used_repeat]
        used_repeat += 1
        return index, zones[0]

    for block in slide.blocks:
        lines = _lines(block)
        if not lines:
            _note_wordless(notes, slide, block, recipe)
            continue
        if _role_of(block) is TextRole.TITLE and title_zone is not None:
            blocks.append(_placed(block, title_zone, lines[0], 0, slide, notes, TextRole.TITLE))
            title_zone = None
            continue
        if isinstance(block, BulletsBlock) and recipe.repeats:
            free_repeats = buckets[used_repeat:]
            placed = 0
            for line, (index, zones) in zip(lines, free_repeats, strict=False):
                blocks.append(_placed(block, zones[0], line, index, slide, notes))
                used_repeat += 1
                placed += 1
            if placed < len(lines):
                _note_lost_lines(notes, slide, block, recipe, placed, len(lines))
            continue
        joined = " ".join(lines)
        zone = _zone_for(block, rest, recipe, slide, notes)
        if zone is not None:
            rest.remove(zone)
            _note_plain(notes, slide, block, recipe)
            blocks.append(_placed(block, zone, joined, 0, slide, notes, _role_of(block)))
            continue
        # Свободных зон не осталось — идём в повтор, пока он есть: пустая карточка
        # рядом со снятым абзацем хуже карточки с абзацем.
        if (taken := take_repeat()) is not None:
            index, card = taken
            _note_plain(notes, slide, block, recipe)
            blocks.append(_placed(block, card, joined, index, slide, notes))
            continue
        _note_drop(notes, slide, block, recipe, seats, wanted)

    return slide.model_copy(
        update={"blocks": blocks, "recipe_id": recipe.recipe_id, "fit_report": {}}
    )
