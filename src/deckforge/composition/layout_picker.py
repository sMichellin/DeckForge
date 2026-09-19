"""Подбор макета: намерение слайда + предпочтения варианта + вместимость.

Change (11) `slide-composition`. Цепочка деградации: сложный макет → простой из того же шаблона.

Макет **никогда не выбирается по имени** (C6): шаблон на защите будет незнакомый, и его
макеты будут называться как угодно. Выбор идёт по виду, который определил классификатор,
и по вместимости, посчитанной парсером.
"""

from __future__ import annotations

import zlib
from typing import Final

from deckforge.domain.enums import LayoutKind, SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.domain.variants import VariantProfile


class LayoutPickError(RuntimeError):
    """В шаблоне нет ни одного макета, пригодного под содержание слайда."""


#: Виды макетов под роль слайда, от предпочтительного к запасному.
#: Соответствие утверждено владельцем потока A; обоснование — в proposal.md.
INTENT_LAYOUTS: Final[dict[SlideIntent, tuple[LayoutKind, ...]]] = {
    SlideIntent.TITLE: (LayoutKind.TITLE,),
    SlideIntent.SECTION: (LayoutKind.SECTION, LayoutKind.TITLE),
    SlideIntent.AGENDA: (LayoutKind.BULLETS, LayoutKind.TWO_COLUMN),
    SlideIntent.PROBLEM: (LayoutKind.BULLETS, LayoutKind.TWO_COLUMN),
    SlideIntent.SOLUTION: (LayoutKind.BULLETS, LayoutKind.TWO_COLUMN),
    SlideIntent.EVIDENCE: (LayoutKind.CHART, LayoutKind.TABLE, LayoutKind.BULLETS),
    SlideIntent.METRICS: (LayoutKind.KPI, LayoutKind.CHART, LayoutKind.TABLE, LayoutKind.BULLETS),
    SlideIntent.COMPARISON: (LayoutKind.TWO_COLUMN, LayoutKind.TABLE, LayoutKind.BULLETS),
    SlideIntent.PROCESS: (LayoutKind.TWO_COLUMN, LayoutKind.BULLETS),
    SlideIntent.ROADMAP: (LayoutKind.TABLE, LayoutKind.TWO_COLUMN, LayoutKind.BULLETS),
    SlideIntent.SUMMARY: (LayoutKind.BULLETS, LayoutKind.KPI, LayoutKind.TWO_COLUMN),
    SlideIntent.CLOSING: (LayoutKind.CLOSING, LayoutKind.TITLE, LayoutKind.SECTION),
}

#: Роли, где вид макета определяется ролью и предпочтение варианта не применяется:
#: титул обязан быть титулом в любом варианте вёрстки.
_STRUCTURAL: Final = frozenset({SlideIntent.TITLE, SlideIntent.SECTION, SlideIntent.CLOSING})

#: Виды, которым нужен свой материал: без него они дают пустую рамку на слайде.
_NEEDS_DATASET: Final = frozenset({LayoutKind.CHART, LayoutKind.TABLE})
_NEEDS_ASSET: Final = frozenset({LayoutKind.IMAGE_FULL})
_NEEDS_FACTS: Final = frozenset({LayoutKind.KPI})


def _slide_can_carry(slide: SlidePlan, kind: LayoutKind) -> bool:
    if kind in _NEEDS_DATASET:
        return slide.dataset_ref is not None
    if kind in _NEEDS_ASSET:
        return bool(slide.asset_refs)
    if kind in _NEEDS_FACTS:
        return bool(slide.fact_refs)
    return True


def _layout_supports(layout: LayoutSpec, kind: LayoutKind) -> bool:
    """Вид макета обещает возможность, вместимость — подтверждает её."""
    capacity = layout.capacity
    if kind == LayoutKind.CHART:
        return capacity.supports_chart
    if kind == LayoutKind.TABLE:
        return capacity.supports_table
    if kind == LayoutKind.IMAGE_FULL:
        return capacity.supports_image
    if kind in {LayoutKind.BULLETS, LayoutKind.TWO_COLUMN, LayoutKind.KPI}:
        return capacity.max_chars_body > 0
    return True


def kind_chain(slide: SlidePlan, variant: VariantProfile) -> list[LayoutKind]:
    """Виды макетов для слайда, от предпочтительного к запасному.

    Предпочтение варианта — **приоритет, а не фильтр**: оно переставляет виды внутри
    цепочки роли и может добавить свой, если слайду есть чем его наполнить. Отбросить
    цепочку роли целиком нельзя: на шаблоне без `kpi` и `image_full` вариант B остался бы
    вообще без макетов.
    """
    chain = list(INTENT_LAYOUTS.get(slide.intent, (LayoutKind.BULLETS,)))
    if slide.intent in _STRUCTURAL:
        return chain

    preferred = [kind for kind in variant.layout_preference if kind in chain]
    extra = [
        kind
        for kind in variant.layout_preference
        if kind not in chain and _slide_can_carry(slide, kind)
    ]
    rest = [kind for kind in chain if kind not in preferred]
    return preferred + extra + rest


#: Сколько разных макетов отводится под содержательные слайды колоды.
#: Двух достаточно, чтобы колода перестала быть двенадцатью одинаковыми подложками,
#: и мало настолько, чтобы она не превратилась в перебор всего шаблона: презентация
#: держится на повторе, а не на разнообразии ради разнообразия.
MAX_CONTENT_LAYOUTS: Final = 2


def _equally_fit(manifest: TemplateManifest, kind: LayoutKind) -> list[LayoutSpec]:
    """Макеты этого вида, между которыми выбор уже не по вместимости.

    Прежде здесь стоял `max(..., key=max_chars_body)`. Пока вместимость у кандидатов
    разная, он прав: вместительный макет даёт меньше поводов деградировать дальше.
    Но на шаблоне без макетов под текст она у всех нулевая, `max` отдаёт первый
    по порядку, и все двенадцать слайдов ложатся на один макет.
    """
    candidates = [
        layout for layout in manifest.layouts_of_kind(kind) if _layout_supports(layout, kind)
    ]
    if not candidates:
        return []
    best = max(layout.capacity.max_chars_body for layout in candidates)
    return [layout for layout in candidates if layout.capacity.max_chars_body == best]


def structural_layout(manifest: TemplateManifest, intent: SlideIntent) -> LayoutSpec | None:
    """Макет, который достанется титулу, перебивке или финалу.

    Отдельная функция, а не побочный результат `pick_layout`: содержательным слайдам
    нужно знать эти макеты, чтобы их не повторять. Титул, встреченный в середине колоды
    ещё раз, читается как начало новой презентации.
    """
    for kind in INTENT_LAYOUTS.get(intent, ()):
        if tied := _equally_fit(manifest, kind):
            return tied[0]
    return None


def _reserved(manifest: TemplateManifest) -> set[str]:
    return {
        layout.layout_id
        for intent in _STRUCTURAL
        if (layout := structural_layout(manifest, intent)) is not None
    }


def _distinct(candidates: list[LayoutSpec], limit: int) -> list[LayoutSpec]:
    """Не больше `limit` макетов, как можно менее похожих друг на друга.

    Похожесть меряется фоном: именно он бросается в глаза, когда колода собрана
    на одной подложке. Фон приехал в манифест вместе с проверкой контраста (#61).
    Когда фоны неразличимы — у VK WorkSpace тринадцать макетов залиты одним `dk1` —
    берутся просто разные макеты: декор и расположение заголовка у них всё равно свои.
    """
    chosen: list[LayoutSpec] = []
    seen_backgrounds: set[str] = set()
    for layout in candidates:
        key = layout.background.color_hex if layout.background is not None else None
        if key is not None and key in seen_backgrounds:
            continue
        chosen.append(layout)
        if key is not None:
            seen_backgrounds.add(key)
        if len(chosen) == limit:
            return chosen
    # Фоны кончились раньше, чем набралось `limit`: добираем по порядку манифеста.
    for layout in candidates:
        if len(chosen) == limit:
            break
        if layout not in chosen:
            chosen.append(layout)
    return chosen


def content_palette(manifest: TemplateManifest, candidates: list[LayoutSpec]) -> list[LayoutSpec]:
    """Макеты под содержательные слайды: разные и не занятые титулом с перебивкой."""
    reserved = _reserved(manifest)
    free = [layout for layout in candidates if layout.layout_id not in reserved]
    # Всё занято структурными ролями — лучше повторить макет, чем остаться без слайда.
    return _distinct(free or candidates, MAX_CONTENT_LAYOUTS)


def _rotation(slide_id: str, size: int) -> int:
    """Номер макета в палитре по слайду. Детерминированно: тот же план — та же колода.

    `slide_id` по схеме плана — `s` и номер, поэтому чередование идёт по порядку слайдов,
    а не по хешу: соседние слайды получают разные подложки, и это видно глазом.
    """
    digits = slide_id[1:]
    # `hash()` строк в Python солится заново в каждом процессе — выбор перестал бы
    # воспроизводиться между прогонами. crc32 от тех же байтов стабилен.
    index = int(digits) if digits.isdigit() else zlib.crc32(slide_id.encode("utf-8"))
    return index % size


def _choose(
    candidates: list[LayoutSpec], slide: SlidePlan, manifest: TemplateManifest
) -> LayoutSpec:
    """Один макет из равно пригодных."""
    if len(candidates) == 1 or slide.intent in _STRUCTURAL:
        return candidates[0]
    palette = content_palette(manifest, candidates)
    return palette[_rotation(slide.slide_id, len(palette))]


def pick_layout(
    slide: SlidePlan, manifest: TemplateManifest, variant: VariantProfile
) -> LayoutSpec:
    """Макет из манифеста под роль слайда. Никогда не по имени — только по виду."""
    for kind in kind_chain(slide, variant):
        if not _slide_can_carry(slide, kind):
            continue
        if tied := _equally_fit(manifest, kind):
            return _choose(tied, slide, manifest)

    return _choose(_last_resort(slide, manifest), slide, manifest)


def _last_resort(slide: SlidePlan, manifest: TemplateManifest) -> list[LayoutSpec]:
    """Ни один вид из цепочки не нашёлся: берём макеты с местом под текст.

    Отказ здесь хуже деградации: колода из одиннадцати слайдов вместо двенадцати —
    это невыполненное задание, а простой макет того же шаблона фирменный стиль не нарушает.

    Возвращается список, а не один макет: выбрать из него — дело `_choose`, и без этого
    на шаблоне, где ни один макет не размечен под текст, вся колода легла бы на первый.
    """
    with_body = [layout for layout in manifest.layouts if layout.capacity.max_chars_body > 0]
    if with_body:
        best = max(layout.capacity.max_chars_body for layout in with_body)
        return [layout for layout in with_body if layout.capacity.max_chars_body == best]
    if manifest.layouts:
        return list(manifest.layouts)
    raise LayoutPickError(f"слайд {slide.slide_id}: в манифесте нет ни одного макета")
