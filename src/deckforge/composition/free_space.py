"""Сколько текста поместится на слайде **мимо** плейсхолдеров. Change (25).

Нужно там, где макет не предусматривает места под основной текст. У VK WorkSpace таких
макетов все пятнадцать: в каждом один плейсхолдер — заголовок, и `capacity.max_chars_body`
у них ноль. Промпт композитора честно сообщал модели «не более 0 знаков в теле», модель
так же честно отдавала один заголовок, и колода выходила из двенадцати заголовков
без единого слова текста (прогоны `b8549ea89984`, `4197f2e8331f`).

Свободное место при этом есть — просто оно не размечено плейсхолдером. Здесь оно
измеряется, чтобы промпт просил ровно столько текста, сколько поместится.

**Место считается тем же решателем, который потом его и отдаст** (`solve_positions`).
Это не совпадение, а условие: посчитай мы площадь иначе, модель получила бы одно число,
а блок — другое место, и расхождение вылезло бы переполнением на этапе вписывания.

**Занятое место обрезается по области контента, а не отбрасывается целиком.** Заголовок
VK WorkSpace шире полей шаблона и начинается выше их: проверка «плейсхолдер целиком внутри
области» его не видит, и свободный блок получал бы всю область контента — вместе с полосой,
где уже лежит заголовок. Пересечение с областью занято, остальное свободно.
"""

from __future__ import annotations

from deckforge.domain.base import BBox
from deckforge.domain.enums import TextRole
from deckforge.domain.template import (
    LayoutCapacity,
    LayoutSpec,
    PlaceholderSpec,
    TemplateManifest,
)
from deckforge.layout.constraints import solve_positions
from deckforge.layout.errors import LayoutFitError
from deckforge.parsing.capacity import chars_that_fit, lines_that_fit

#: Метка свободного блока в запросе к решателю. Наружу не выходит.
_PROBE = "__free__"


def clip(box: BBox, area: BBox) -> BBox | None:
    """Часть блока, попавшая в область. `None` — не пересекаются вовсе."""
    x0, y0 = max(box.x, area.x), max(box.y, area.y)
    x1, y1 = min(box.right, area.right), min(box.bottom, area.bottom)
    if x1 <= x0 or y1 <= y0:
        return None
    return BBox(x=x0, y=y0, cx=x1 - x0, cy=y1 - y0)


def has_body_slot(layout: LayoutSpec) -> bool:
    """Макет предусматривает место под основной текст."""
    return layout.capacity.max_chars_body > 0


def free_area(layout: LayoutSpec, manifest: TemplateManifest) -> BBox | None:
    """Наибольший прямоугольник области контента, свободный от плейсхолдеров макета.

    Считается по **всем** плейсхолдерам: на этапе промпта ещё неизвестно, какие из них
    модель займёт, а обещать место, которое потом заберёт заголовок, нельзя.
    """
    content = manifest.content_bbox
    fixed: list[tuple[str, BBox | None]] = [
        (f"ph{ph.idx}", clipped)
        for ph in layout.placeholders
        if (clipped := clip(ph.bbox, content)) is not None
    ]
    try:
        boxes = solve_positions([*fixed, (_PROBE, None)], manifest)
    except LayoutFitError:
        return None
    return boxes.get(_PROBE)


def free_capacity(layout: LayoutSpec, manifest: TemplateManifest) -> LayoutCapacity:
    """Вместимость свободного места макета — в тех же единицах, что `layout.capacity`.

    Оценка по средней ширине знака, как и у парсера: промпту нужен порядок величины,
    а точное вписывание делает слой `layout` перед записью файла.
    """
    area = free_area(layout, manifest)
    body = manifest.typography(TextRole.BODY)
    body_pt = body.size_pt if body is not None else 0.0
    if area is None or body_pt <= 0:
        return layout.capacity

    # `chars_that_fit` меряет плейсхолдер, а меряем мы прямоугольник: разница только
    # в имени типа, поля текстовой рамки те же самые.
    probe = PlaceholderSpec(
        idx=0, ph_type="BODY", role=TextRole.BODY, x=area.x, y=area.y, cx=area.cx, cy=area.cy
    )
    return layout.capacity.model_copy(
        update={
            "max_chars_body": chars_that_fit(probe, body_pt),
            "max_bullets": lines_that_fit(probe, body_pt),
        }
    )


def effective_capacity(layout: LayoutSpec, manifest: TemplateManifest) -> LayoutCapacity:
    """Вместимость, которую видит промпт: своя у макета, иначе — свободного места."""
    return layout.capacity if has_body_slot(layout) else free_capacity(layout, manifest)


#: Какую долю ширины области контента должна занимать свободная зона, чтобы её стоило
#: предлагать под отдельный блок. Та же величина, которой нас меряет C9 («пустая зона
#: ≥ 40 % ширины»): зона, из-за которой мы получаем находку, и зона, которую мы просим
#: занять, обязаны быть одной и той же.
ZONE_MIN_WIDTH_SHARE = 0.4

#: Сколько строк зона должна держать. Полоса в одну строку — не место под блок: на
#: VK Education s05 свободный блок `smartart` получил 30 × 1,5 см и не влез ни в каком
#: кегле, схема выродилась в список (A13, прогон add3de1e5918).
ZONE_MIN_LINES = 3


def spare_zone(layout: LayoutSpec, manifest: TemplateManifest) -> LayoutCapacity | None:
    """Свободная зона, которую стоит предложить **вдобавок** к месту под тело. Задача B10.

    У макета либо есть место под тело, либо нет. Когда нет, свободная часть слайда и есть
    тело (`effective_capacity`, change 25) — здесь не о ней. Когда есть, свободная часть
    до сих пор не предлагалась никому, и на шаблонах кейса это половина слайда: у VK Tech
    место под тело обещает промпту 874 знака, а рядом лежит зона 12,4 × 9,4 см ещё
    на 954 знака; у VK Education обещают 76 знаков при свободных 648.

    Зона предлагается, только если она **широкая и высокая разом**. Узкая полоса во всю
    ширину — это воздух между блоками, а не место: ставить в неё блок значит менять пустоту
    на переполнение.
    """
    if not has_body_slot(layout):
        return None
    area = free_area(layout, manifest)
    if area is None or area.cx < manifest.content_bbox.cx * ZONE_MIN_WIDTH_SHARE:
        return None
    capacity = free_capacity(layout, manifest)
    return capacity if capacity.max_bullets >= ZONE_MIN_LINES else None
