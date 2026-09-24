"""Текст колоды по зонам композиции. Change `compose-by-the-recipe`, таск 05b.

Модель пишет содержание, как писала: заголовок, пункты, абзац. Разложить их по зонам
шаблона — счёт, а не решение модели: зоны различаются номером повтора и ступенью
лестницы, и это те же числа, что уже посчитал каталог композиций.

Пункт списка становится отдельным блоком на свой повтор: у шаблона ряд из трёх карточек,
а не один список на три строки, и вёрстка кладёт в каждую карточку свой текст.
"""

from __future__ import annotations

from deckforge.composition.recipe_picker import KEEP_SHARE
from deckforge.designsystem.models import Recipe, TypeLevel, Zone
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import Block, BulletsBlock, SlideIR, TextBlock

#: Ступени, которые несут заголовок внутри повтора: у карточки это её название.
#: Заголовка слайда здесь нет: он один на слайд и повтору не принадлежит, даже если
#: каталог отнёс его рамку к ряду.
CARD_TITLES = (TypeLevel.CARD_TITLE, TypeLevel.SECTION_SUBTITLE)


def _title_zone(recipe: Recipe) -> Zone | None:
    """Зона заголовка слайда — по всем зонам, не только свободным.

    Ищем везде, потому что заголовок обязан получить заголовок: зона заголовка, попавшая
    в повтор, — это ошибка замера, и платить за неё пунктом списка в шапке слайда нельзя.
    """
    titles = [zone for zone in recipe.zones if zone.role is TypeLevel.SLIDE_TITLE]
    return max(titles, key=lambda zone: (zone.size_pt or 0, zone.zone_id)) if titles else None


def _zones_of_repeat(recipe: Recipe, index: int, *, skip: Zone | None = None) -> list[Zone]:
    """Зоны одного повтора, от заголовка карточки к её тексту."""
    same = [zone for zone in recipe.zones if zone.repeat == index and zone is not skip]
    return sorted(same, key=lambda zone: (zone.role not in CARD_TITLES, zone.zone_id))


def _free_zones(recipe: Recipe) -> list[Zone]:
    """Зоны вне повторов, от крупной к мелкой: заголовок слайда, лид, подпись."""
    ladder = list(TypeLevel)
    free = [zone for zone in recipe.zones if zone.repeat is None]
    return sorted(free, key=lambda zone: (ladder.index(zone.role), zone.zone_id))


def _buckets(recipe: Recipe, heading: Zone | None) -> list[tuple[int, list[Zone]]]:
    """Повторы, которым есть куда писать: номер повтора и его зоны.

    Повтор без своих зон пропускается, а не обрывает раскладку: иначе один пустой повтор
    в середине ряда съедал бы все оставшиеся пункты списка.
    """
    numbered = (
        (index, _zones_of_repeat(recipe, index, skip=heading))
        for index in range(recipe.repeats)
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


def _in_zone(block: Block, zone: Zone, text: str, index: int) -> TextBlock:
    """Блок, стоящий в зоне шаблона: без координат и плейсхолдера — рамку дал автор."""
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
) -> TextBlock:
    """Блок в зоне, с оговоркой, если от текста осталось меньше половины."""
    placed = _in_zone(block, zone, text, index)
    _note_clip(notes, slide, placed, text)
    return placed


def bind_to_recipe(
    slide: SlideIR, recipe: Recipe, notes: list[str] | None = None
) -> SlideIR:
    """Разложить текст слайда по зонам композиции.

    Заголовок идёт в зону заголовка, пункты — по одному на повтор, остальной текст —
    в свободные зоны по убыванию ступени. Блок, которому зоны не досталось, из слайда
    уходит: вёрстка его всё равно не нарисует, а в отчёте он выглядел бы как поставленный.

    `notes` получает обрезку, от которой осталось меньше половины текста (RG23).
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
        if getattr(block, "role", None) is TextRole.TITLE and title_zone is not None:
            blocks.append(_placed(block, title_zone, lines[0], 0, slide, notes))
            title_zone = None
            continue
        if isinstance(block, BulletsBlock) and recipe.repeats:
            free_repeats = _buckets(recipe, heading)[used_repeat:]
            for line, (index, zones) in zip(lines, free_repeats, strict=False):
                blocks.append(_placed(block, zones[0], line, index, slide, notes))
                used_repeat += 1
            continue
        if rest:
            joined = " ".join(lines)
            blocks.append(_placed(block, rest.pop(0), joined, 0, slide, notes))

    return slide.model_copy(
        update={"blocks": blocks, "recipe_id": recipe.recipe_id, "fit_report": {}}
    )
