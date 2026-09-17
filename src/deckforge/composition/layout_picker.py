"""Подбор макета: намерение слайда + предпочтения варианта + вместимость.

Change (11) `slide-composition`. Цепочка деградации: сложный макет → простой из того же шаблона.

Макет **никогда не выбирается по имени** (C6): шаблон на защите будет незнакомый, и его
макеты будут называться как угодно. Выбор идёт по виду, который определил классификатор,
и по вместимости, посчитанной парсером.
"""

from __future__ import annotations

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


def pick_layout(
    slide: SlidePlan, manifest: TemplateManifest, variant: VariantProfile
) -> LayoutSpec:
    """Макет из манифеста под роль слайда. Никогда не по имени — только по виду."""
    for kind in kind_chain(slide, variant):
        if not _slide_can_carry(slide, kind):
            continue
        candidates = [
            layout for layout in manifest.layouts_of_kind(kind) if _layout_supports(layout, kind)
        ]
        if candidates:
            # Из одинаковых по виду берём вместительный: меньше поводов деградировать дальше.
            return max(candidates, key=lambda item: item.capacity.max_chars_body)

    return _last_resort(slide, manifest)


def _last_resort(slide: SlidePlan, manifest: TemplateManifest) -> LayoutSpec:
    """Ни один вид из цепочки не нашёлся: берём любой макет с местом под текст.

    Отказ здесь хуже деградации: колода из одиннадцати слайдов вместо двенадцати —
    это невыполненное задание, а простой макет того же шаблона фирменный стиль не нарушает.
    """
    with_body = [layout for layout in manifest.layouts if layout.capacity.max_chars_body > 0]
    if with_body:
        return max(with_body, key=lambda item: item.capacity.max_chars_body)
    if manifest.layouts:
        return manifest.layouts[0]
    raise LayoutPickError(f"слайд {slide.slide_id}: в манифесте нет ни одного макета")
