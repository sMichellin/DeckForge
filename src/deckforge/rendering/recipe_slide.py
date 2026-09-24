"""Слайд по рецепту: копия слайда-примера шаблона. Change `recipe-slide-in-the-writer`.

Раньше writer строил каждый слайд из пустого макета, а слайды-примеры удалял первым делом.
Но оформление шаблона живёт не в макетах: вне плейсхолдеров стоит от 87 до 96 % содержимого
примеров. Пустой макет — это белый фон с рамками под текст, и «вёрстка по дизайн-системе»
поверх него плашек автора не вернёт.

Здесь пример копируется целиком — с фоном, плашками, декором, картинками и порядком
наложения, — а наш текст занимает его текстовые зоны. Модель файла по-прежнему не видит
(ADR-003, пересмотр 23.09): она пишет только `SlideIR` с `zone_id`, а копирует writer.

Фигуры остаются нативными объектами PowerPoint: ни картинки слайда, ни растра —
правило C3 цело.
"""

from __future__ import annotations

import copy
from typing import Any

from lxml import etree
from pptx.oxml.ns import qn

from deckforge.designsystem.models import Recipe, TypeLevel
from deckforge.domain.slide import Block, BulletsBlock, SlideIR, TextBlock

#: Атрибуты, которыми фигура ссылается на связь своей части: картинка, диаграмма, ссылка.
#: При копировании они переписываются на связи нового слайда, иначе PowerPoint предложит
#: «восстановить» файл.
REL_ATTRS = (qn("r:embed"), qn("r:id"), qn("r:link"))

#: Узлы дерева фигур, которые у нового слайда уже свои.
OWN_NODES = (qn("p:nvGrpSpPr"), qn("p:grpSpPr"))

#: Фигуры, которые адресует каталог рецептов по `cNvPr id`. Тот же набор, что берёт разбор
#: примеров (`parsing/ooxml/examples._collect`): группы раскрываются, сами не адресуются.
SHAPE_TAGS = (qn("p:sp"), qn("p:pic"), qn("p:cxnSp"), qn("p:graphicFrame"))
GROUP = qn("p:grpSp")


class RecipeError(ValueError):
    """Рецепт не удалось применить: примера нет в файле или зоны не нашлись."""


def _part_name(slide: Any) -> str:
    return str(slide.part.partname).lstrip("/")


def source_slide(prs: Any, recipe: Recipe) -> Any:
    """Слайд-пример шаблона по имени части. Порядок в `sldIdLst` ненадёжен, имя — нет."""
    for slide in prs.slides:
        if _part_name(slide) == (recipe.part_name or "").lstrip("/"):
            return slide
    raise RecipeError(f"рецепт {recipe.recipe_id}: части {recipe.part_name} нет в шаблоне")


def _shapes_tree(slide: Any) -> Any:
    return slide.shapes._spTree


def _xml_id(node: Any) -> int | None:
    name = node.find(f"./*/{qn('p:cNvPr')}")
    if name is None:
        return None
    raw = name.get("id")
    return int(raw) if raw and raw.isdigit() else None


def _shapes_in(parent: Any) -> Any:
    """Фигуры в порядке документа, группы раскрыты — так же, как их видит разбор примеров."""
    for node in parent:
        if node.tag == GROUP:
            yield from _shapes_in(node)
        elif node.tag in SHAPE_TAGS:
            yield node


def _addressed(recipe: Recipe) -> set[int]:
    ids = {zone.xml_id for zone in recipe.zones if zone.xml_id is not None}
    ids.update(xml_id for row in recipe.repeat_xml_ids for xml_id in row)
    if recipe.picture_xml_id is not None:
        ids.add(recipe.picture_xml_id)
    return ids


def _by_xml_id(tree: Any, recipe: Recipe) -> dict[int, Any]:
    """Фигуры слайда по их `cNvPr id` на любой глубине групп.

    Каталог делает зонами и фигуры внутри `p:grpSp` — подписи карточек, строки таймлайна.
    Ищи writer только верхний уровень, такая зона молча пропускалась бы: наш текст
    терялся, а текст шаблона оставался.

    Если id, который адресует рецепт, в примере повторяется, какую фигуру имел в виду
    каталог, неизвестно: писать наугад — значит молча оставить чужую фразу. Это ошибка.
    """
    found: dict[int, Any] = {}
    twins: set[int] = set()
    for node in _shapes_in(tree):
        identifier = _xml_id(node)
        if identifier is None:
            continue
        if identifier in found:
            twins.add(identifier)
        found.setdefault(identifier, node)
    ambiguous = sorted(twins & _addressed(recipe))
    if ambiguous:
        raise RecipeError(
            f"рецепт {recipe.recipe_id}: cNvPr id {ambiguous} повторяется в примере, "
            "фигуру зоны не определить"
        )
    return found


def _relink(source: Any, target: Any) -> None:
    """Перевесить связи скопированных фигур на новый слайд.

    Картинка и диаграмма живут отдельными частями пакета; копия ссылается на них тем же
    `rId`, которого у нового слайда нет. Части при этом переиспользуются, а не дублируются.
    """
    rels = source.part.rels
    mapping: dict[str, str] = {}
    for node in _shapes_tree(target).iter():
        for attr in REL_ATTRS:
            old = node.get(attr)
            if not old:
                continue
            if old not in mapping:
                rel = rels[old]
                mapping[old] = (
                    target.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
                    if rel.is_external
                    else target.part.relate_to(rel.target_part, rel.reltype)
                )
            node.set(attr, mapping[old])


def clone_slide(prs: Any, recipe: Recipe) -> Any:
    """Копия слайда-примера: тот же макет, те же фигуры, свои связи."""
    source = source_slide(prs, recipe)
    target = prs.slides.add_slide(source.slide_layout)

    tree = _shapes_tree(target)
    for node in list(tree):
        if node.tag not in OWN_NODES:
            tree.remove(node)
    for node in _shapes_tree(source):
        if node.tag not in OWN_NODES:
            tree.append(copy.deepcopy(node))

    _relink(source, target)
    return target


def _first_run_props(shape: Any) -> Any | None:
    """Свойства первого прогона зоны: гарнитура, кегль и цвет, которые поставил автор."""
    body = shape.find(qn("p:txBody"))
    if body is None:
        return None
    props = body.find(f"{qn('a:p')}/{qn('a:r')}/{qn('a:rPr')}")
    return copy.deepcopy(props) if props is not None else None


def _paragraph_props(shape: Any) -> Any | None:
    body = shape.find(qn("p:txBody"))
    if body is None:
        return None
    props = body.find(f"{qn('a:p')}/{qn('a:pPr')}")
    return copy.deepcopy(props) if props is not None else None


def _lines_of(block: Block) -> list[str]:
    if isinstance(block, BulletsBlock):
        return [item.text for item in block.items if item.text]
    if isinstance(block, TextBlock):
        return [line for line in block.text.splitlines() if line]
    return []


def write_zone(shape: Any, lines: list[str]) -> None:
    """Заменить текст зоны нашим, сохранив оформление автора.

    Берутся свойства первого прогона и первого абзаца: кегль, гарнитура и цвет остаются
    теми, что в шаблоне (правила 5 и 6 — в IR их нет вовсе).
    """
    body = shape.find(qn("p:txBody"))
    if body is None:
        return
    run_props, par_props = _first_run_props(shape), _paragraph_props(shape)
    for paragraph in body.findall(qn("a:p")):
        body.remove(paragraph)
    for line in lines or [""]:
        paragraph = etree.SubElement(body, qn("a:p"))
        if par_props is not None:
            paragraph.append(copy.deepcopy(par_props))
        run = etree.SubElement(paragraph, qn("a:r"))
        if run_props is not None:
            run.append(copy.deepcopy(run_props))
        text = etree.SubElement(run, qn("a:t"))
        text.text = line


def _used_repeats(recipe: Recipe, blocks: list[Block]) -> int:
    """Сколько повторов занято нашим текстом. Ноль — ряд не используется вовсе."""
    zones = {zone.zone_id: zone for zone in recipe.zones}
    used: list[int] = []
    for block in blocks:
        zone_id = getattr(block, "zone_id", None)
        zone = zones.get(zone_id) if zone_id else None
        if zone is not None and zone.repeat is not None:
            used.append(zone.repeat)
    return max(used) + 1 if used else 0


def clone_recipe(prs: Any, recipe: Recipe, slide_ir: SlideIR) -> Any:
    """Слайд колоды по рецепту: копия примера, наш текст по зонам, лишнее удалено."""
    slide = clone_slide(prs, recipe)
    shapes = _by_xml_id(_shapes_tree(slide), recipe)

    filled: set[str] = set()
    for block in slide_ir.blocks:
        zone_id = getattr(block, "zone_id", None)
        if not zone_id:
            continue
        zone = next((z for z in recipe.zones if z.zone_id == zone_id), None)
        if zone is None or zone.xml_id is None or zone.xml_id not in shapes:
            continue
        write_zone(shapes[zone.xml_id], _lines_of(block))
        filled.add(zone_id)

    _drop_spare_repeats(recipe, _used_repeats(recipe, list(slide_ir.blocks)), shapes)
    _drop_empty_zones(recipe, filled, shapes)
    return slide


def _remove(node: Any) -> None:
    """Удалить фигуру у её собственного родителя. Группа, в которой не осталось ничего,
    кроме её собственных свойств, уходит следом: пустая рамка группы на слайде ни к чему.
    Всё прочее в группе (`p:contentPart`, `mc:AlternateContent`) не наше — группа остаётся."""
    parent = node.getparent() if node is not None else None
    if parent is None:
        return
    parent.remove(node)
    if parent.tag == GROUP and all(child.tag in OWN_NODES for child in parent):
        _remove(parent)


def _drop_spare_repeats(recipe: Recipe, used: int, shapes: dict[int, Any]) -> None:
    """Лишние повторы удаляются целиком и с конца ряда: плашка вместе со своим текстом."""
    if not recipe.repeat_xml_ids:
        return
    for row in recipe.repeat_xml_ids[max(used, 0) :]:
        for xml_id in row:
            _remove(shapes.get(xml_id))


def _drop_empty_zones(recipe: Recipe, filled: set[str], shapes: dict[int, Any]) -> None:
    """Зона без нашего текста удаляется — иначе в колоде останется текст шаблона.

    Заголовок не удаляется никогда: слайд без заголовка читать нечем, и пустую рамку
    заметит человек, а чужую фразу — нет.
    """
    for zone in recipe.zones:
        if zone.zone_id in filled or zone.xml_id is None or zone.xml_id not in shapes:
            continue
        #: Зона внутри уцелевшего повтора и заголовок остаются на месте, но чужую фразу
        #: в них стираем: пустая рамка видна человеку, а текст шаблона в колоде — нет
        #: (проверка `template.sample_text_left`). Пустая зона вне повтора удаляется:
        #: держать пустую рамку посреди слайда незачем.
        if zone.repeat is not None or zone.role is TypeLevel.SLIDE_TITLE:
            write_zone(shapes[zone.xml_id], [])
            continue
        _remove(shapes[zone.xml_id])
