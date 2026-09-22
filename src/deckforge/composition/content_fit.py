"""Пригодность макета под схему содержания слайда. Задача B8.

Среди макетов одного вида побеждал наибольший `capacity.max_chars_body`. Он считается
по **всем** содержательным плейсхолдерам, включая `PIC`, `CHART` и `TBL`
(`parsing/capacity.py`), — поэтому макет «под диаграмму» выглядел самым вместительным
и на слайде, у которого нет ни одного набора данных. Диаграмма там не появлялась
(композитор отбрасывает блок без материала), текст уходил в тело, а место под диаграмму
оставалось пустым: прогон `1d0bc29cf23f` — левые 60 % слайда, `f0b9ff6f0a74` — правая
половина на семи слайдах из десяти.

SlideTailor ([arXiv:2512.20292](https://arxiv.org/html/2512.20292v1)) называет это прямо:
«large areas of unreasonable blank space» и оставленные плейсхолдеры шаблона — известный
провал PPTAgent. Лечится не вёрсткой, а выбором макета: PPTAgent
([arXiv:2501.03936](https://arxiv.org/html/2501.03936v1)) описывает элемент макета тройкой
«категория, модальность, содержание» и берёт макет, чья схема совпадает с тем, что у слайда
есть. Здесь ровно это: место, которое **этому** слайду нечем занять, вместимостью
не считается и вдобавок штрафуется своей площадью.

Признаки — только из манифеста и плана (C6): ни имён макетов, ни цветов, ни размеров
шаблона в коде.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Final

from deckforge.composition.free_space import clip
from deckforge.domain.base import BBox
from deckforge.domain.enums import TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import LayoutSpec, PlaceholderSpec, TemplateManifest
from deckforge.parsing.capacity import CONTENT_PH_TYPES, chars_that_fit

#: Места, которым нужен свой материал. Без него композитор отбрасывает блок
#: (`composer._bind`: «нет такого набора данных», «нет такого ассета»), и место
#: остаётся ничьим: ни диаграммы, ни текста.
_NEEDS_DATASET_PH: Final = frozenset({"CHART", "TBL"})
_NEEDS_ASSET_PH: Final = frozenset({"PIC"})

#: Шаг, с которым сравнивается доля мёртвого места. Без допуска макет с декоративной
#: рамкой под значок проигрывал бы тесному макету из-за третьего знака доли, а разница
#: между «полслайда пусто» и «уголок пусто» — это десятые, а не тысячные.
_DEAD_STEP: Final = 0.1


def can_fill(placeholder: PlaceholderSpec, slide: SlidePlan) -> bool:
    """Слайду есть чем занять это место."""
    if placeholder.ph_type in _NEEDS_DATASET_PH:
        return slide.dataset_ref is not None
    if placeholder.ph_type in _NEEDS_ASSET_PH:
        return bool(slide.asset_refs)
    return True


def dead_share(layout: LayoutSpec, manifest: TemplateManifest, slide: SlidePlan) -> float:
    """Доля области контента под местами, которые этому слайду нечем занять.

    Считается по видимой части места: плейсхолдер бывает шире полей шаблона, и снаружи
    области контента его площадь никого не интересует. Перекрывающиеся места сложатся
    дважды — в шаблонах кейса их нет, а доля всё равно обрезана единицей.
    """
    content = manifest.content_bbox
    area = content.cx * content.cy
    if area <= 0:
        return 0.0
    dead = sum(
        box.cx * box.cy
        for placeholder in layout.placeholders
        if not can_fill(placeholder, slide)
        and (box := clip(placeholder.bbox, content)) is not None
    )
    return min(1.0, dead / area)


def dead_bucket(layout: LayoutSpec, manifest: TemplateManifest, slide: SlidePlan) -> int:
    """`dead_share` с точностью до десятой — то, по чему макеты сравниваются."""
    return int(dead_share(layout, manifest, slide) / _DEAD_STEP)


def fillable_chars(layout: LayoutSpec, manifest: TemplateManifest, slide: SlidePlan) -> int:
    """`max_chars_body`, посчитанный только по местам, которые слайд может занять.

    Свободное место сюда **не** добавляется, и это важно: у VK WorkSpace во всех
    пятнадцати макетах один плейсхолдер — заголовок, своей вместимости у них нет ни у кого,
    и все они остаются равно пригодными. Начни мы здесь мерить свободное место, равенство
    рассыпалось бы на пятнадцать разных чисел и вся колода легла бы на один макет.
    """
    body = manifest.typography(TextRole.BODY)
    body_pt = body.size_pt if body is not None else 0.0
    if body_pt <= 0:
        return layout.capacity.max_chars_body
    return sum(
        chars_that_fit(placeholder, body_pt)
        for placeholder in layout.placeholders
        if placeholder.ph_type in CONTENT_PH_TYPES and can_fill(placeholder, slide)
    )


def _union_area(boxes: list[BBox]) -> int:
    """Площадь объединения прямоугольников — точная, без двойного счёта пересечений.

    Сжатие координат: стороны любого куска объединения лежат на краях прямоугольников,
    поэтому достаточно перебрать полосы между краями. Мест на макете единицы — перебор
    дешевле любой хитрости.
    """
    if not boxes:
        return 0
    xs = sorted({value for box in boxes for value in (box.x, box.right)})
    ys = sorted({value for box in boxes for value in (box.y, box.bottom)})
    return sum(
        (x1 - x0) * (y1 - y0)
        for x0, x1 in pairwise(xs)
        for y0, y1 in pairwise(ys)
        if any(
            box.x <= x0 and box.right >= x1 and box.y <= y0 and box.bottom >= y1
            for box in boxes
        )
    )


def covered_share(layout: LayoutSpec, manifest: TemplateManifest, slide: SlidePlan) -> float:
    """Какую долю области контента покрывают места, которые слайд может занять.

    Не то же, что вместимость в знаках: `max_chars_body` растёт и от узкой высокой полосы,
    а пустая половина слайда — это про **площадь**. Замер по шаблонам кейса: у VK Tech
    содержательные макеты покрывают 13–49 % области контента, медиана 26 %, и именно этот
    разброс отличает макет, на котором слайд выглядит полным, от макета с пустой половиной.
    """
    content = manifest.content_bbox
    area = content.cx * content.cy
    if area <= 0:
        return 0.0
    boxes = [
        box
        for placeholder in layout.placeholders
        if can_fill(placeholder, slide) and (box := clip(placeholder.bbox, content)) is not None
    ]
    return min(1.0, _union_area(boxes) / area)


def best_by_content(
    candidates: list[LayoutSpec], manifest: TemplateManifest, slide: SlidePlan
) -> list[LayoutSpec]:
    """Равно пригодные макеты под схему этого слайда.

    Сначала отбрасываются те, у кого мёртвого места заметно больше, затем среди
    оставшихся берутся самые вместительные — тот же порядок, что был до B8, только
    вместимость теперь считается по живым местам.
    """
    if not candidates:
        return []
    least = min(dead_bucket(layout, manifest, slide) for layout in candidates)
    alive = [
        layout for layout in candidates if dead_bucket(layout, manifest, slide) == least
    ]
    best = max(fillable_chars(layout, manifest, slide) for layout in alive)
    return [layout for layout in alive if fillable_chars(layout, manifest, slide) == best]
