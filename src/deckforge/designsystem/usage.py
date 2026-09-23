"""Что из дизайн-системы шаблона стоит на колоде. Change `design-system-usage-in-the-run`.

До этого change в `run.json` были числа разделов ДС (DG2), то есть видно было, что ДС
**собрана**. Собрана ли по ней **колода**, по отчёту сказать было нельзя: прогон 23.09
пришлось смотреть глазами, чтобы понять, что ДС «не встроена в общий процесс».

Элемент ДС здесь — блок, который вёрстка рисует по дизайн-системе, а не по плейсхолдеру
(`layout/by_design.py`): показатель (кегль числа), схема (плитка из каталога компонентов),
цитата и callout (полоса и отбивка), нумерованный и иконочный список (знак и отступ).
Абзац и маркированный список — не элементы ДС: их оформляет макет шаблона.

Функции чистые: ни модели, ни файлов. Слой стоит над `domain` и импортирует только его.
"""

from __future__ import annotations

from deckforge.designsystem.models import DesignSystem
from deckforge.domain.enums import ListStyle
from deckforge.domain.slide import (
    Block,
    BulletsBlock,
    CalloutBlock,
    DeckIR,
    KpiBlock,
    QuoteBlock,
    SlideIR,
    SmartArtBlock,
)

#: Элемент колоды → вид элемента в `DesignSystem.synthesized`, по которому вёрстка его
#: рисует. У показателя и схемы вида в `synthesized` нет: их ДС задаёт кеглем числа
#: и каталогом компонентов, и нарисовать их вёрстка может на любом шаблоне.
_SYNTH_KIND: dict[str, str | None] = {
    "kpi": None,
    "smartart": None,
    "quote": "quote",
    "callout:insight": "callout_insight",
    "callout:risk": "callout_risk",
    f"bullets:{ListStyle.NUMBERED.value}": ListStyle.NUMBERED.value,
    f"bullets:{ListStyle.ICON.value}": ListStyle.ICON.value,
}


def element_of(block: Block) -> str | None:
    """Имя элемента ДС, которым нарисован блок; `None` — блок оформляет макет."""
    if isinstance(block, KpiBlock):
        return "kpi"
    if isinstance(block, SmartArtBlock):
        return "smartart"
    if isinstance(block, QuoteBlock):
        return "quote"
    if isinstance(block, CalloutBlock):
        return f"callout:{block.tone.value}"
    if isinstance(block, BulletsBlock) and block.style in (ListStyle.NUMBERED, ListStyle.ICON):
        return f"bullets:{block.style.value}"
    return None


def slide_elements(slide: SlideIR) -> list[str]:
    """Элементы ДС на слайде, в порядке блоков, без повторов."""
    found: list[str] = []
    for block in slide.blocks:
        name = element_of(block)
        if name is not None and name not in found:
            found.append(name)
    return found


def available(ds: DesignSystem) -> list[str]:
    """Элементы, которые ДС этого шаблона умеет рисовать. Порядок — порядок `_SYNTH_KIND`."""
    kinds = {item.kind for item in ds.synthesized}
    return [name for name, kind in _SYNTH_KIND.items() if kind is None or kind in kinds]


def usage(deck: DeckIR, ds: DesignSystem | None) -> dict[str, object]:
    """Сводка для `run.json`: какие элементы ДС стоят на каком слайде и чего нет нигде.

    `share` — доля слайдов, на которых есть хотя бы один элемент ДС: по ней прогоны
    сравниваются между собой (`scripts/run_metrics.py`). `unused` — что ДС умеет,
    а колода не взяла ни разу: это список вопросов к плану, а не ошибка — не каждой
    колоде нужна цитата.
    """
    by_slide = {slide.slide_id: slide_elements(slide) for slide in deck.slides}
    counts: dict[str, int] = {}
    for names in by_slide.values():
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    total = len(deck.slides)
    with_elements = sum(1 for names in by_slide.values() if names)
    can = available(ds) if ds is not None else []
    return {
        "slides": by_slide,
        "slides_total": total,
        "slides_with_elements": with_elements,
        "share": round(with_elements / total, 3) if total else 0.0,
        "elements": {name: counts[name] for name in sorted(counts)},
        "unused": [name for name in can if name not in counts],
    }
