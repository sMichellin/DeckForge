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

from deckforge.composition.recipe_picker import KEEP_SHARE
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import Block, BulletsBlock, SlideIR, TextBlock

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


def _zones_of_repeat(recipe: Recipe, index: int, *, skip: Zone | None = None) -> list[Zone]:
    """Зоны одного повтора, от заголовка карточки к её тексту."""
    same = [zone for zone in recipe.zones if zone.repeat == index and zone is not skip]
    return sorted(same, key=lambda zone: (zone.role not in CARD_TITLES, zone.zone_id))


def _free_zones(recipe: Recipe) -> list[Zone]:
    """Зоны вне повторов. Порядок им не нужен: зону под блок выбирает `_zone_for`."""
    return [zone for zone in recipe.zones if zone.repeat is None]


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
    if isinstance(block, BulletsBlock):
        return [item.text for item in block.items if item.text.strip()]
    if isinstance(block, TextBlock):
        return [line for line in block.text.splitlines() if line.strip()]
    return []


def _clip(text: str, limit: int) -> str:
    """Обрезать по словам до вместимости зоны. Зона — рамка автора, растянуть её нельзя.

    Лимит ноль означает, что вместимость посчитать не удалось: тогда не режем.
    """
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
        text=_clip(text, zone.capacity_chars),
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
    поставленный.

    `notes` получает обрезку, от которой осталось меньше половины текста (RG23), и блок,
    вставший в зону чужой ступени (RG30).
    """
    heading = _title_zone(recipe)
    title_zone = heading
    rest = [zone for zone in _free_zones(recipe) if zone is not heading]

    blocks: list[Block] = []
    used_repeat = 0
    for block in slide.blocks:
        lines = _lines(block)
        if not lines:
            continue
        if _role_of(block) is TextRole.TITLE and title_zone is not None:
            blocks.append(_placed(block, title_zone, lines[0], 0, slide, notes, TextRole.TITLE))
            title_zone = None
            continue
        if isinstance(block, BulletsBlock) and recipe.repeats:
            free_repeats = _buckets(recipe, heading)[used_repeat:]
            for line, (index, zones) in zip(lines, free_repeats, strict=False):
                blocks.append(_placed(block, zones[0], line, index, slide, notes))
                used_repeat += 1
            continue
        zone = _zone_for(block, rest, recipe, slide, notes)
        if zone is not None:
            rest.remove(zone)
            joined = " ".join(lines)
            blocks.append(_placed(block, zone, joined, 0, slide, notes, _role_of(block)))

    return slide.model_copy(
        update={"blocks": blocks, "recipe_id": recipe.recipe_id, "fit_report": {}}
    )
