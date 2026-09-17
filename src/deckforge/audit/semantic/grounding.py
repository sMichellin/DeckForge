"""`content.numbers_grounded` — фактчекинг чисел. Change (18) `audit-semantic`.

Проверка объявлена **детерминированной**, хотя лежит в `semantic/`: спрашивать VLM
«все ли цифры настоящие» бессмысленно — исходных материалов она не видит и может лишь
согласиться с тем, что написано на слайде. Числа извлекаются из текста слайда тем же
разбором, что и из контента (change 7), и сверяются с `ContentPackage.facts[].numbers`.

Заодно это один из рычагов бюджета: вопрос про числа стоил бы 12 вызовов VLM на колоду
из 12 слайдов, а при трёх прогонах — 36.

Форматные расхождения («37 %» против доли 0.37) разрешаются арифметикой, а не моделью:
проценты и доли — одно и то же число в разных единицах, и путать их с настоящим
расхождением нельзя.
"""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import block_bbox, block_text, layout_of
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.domain.audit import Finding
from deckforge.domain.content import Number
from deckforge.domain.enums import Severity
from deckforge.parsing.content import extract_numbers

#: Допуск сравнения: числа на слайде округляют, «37,5 %» превращается в «38 %».
_TOLERANCE = 0.51


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= _TOLERANCE


def grounded_in(number: Number, sources: list[Number]) -> bool:
    """Есть ли число в исходных материалах — с учётом формата записи.

    Совпадение ищется по значению, а не по строке: на слайде «37 %», в источнике
    может лежать 0.37. Это одно и то же число, и находкой быть не должно.
    """
    for source in sources:
        if _close(number.value, source.value):
            return True
        # Процент против доли: 37 % ↔ 0.37. Сотая часть — не опечатка, а единица.
        if _close(number.value, source.value * 100) or _close(number.value * 100, source.value):
            return True
    return False


@check(id="content.numbers_grounded", deterministic=True, severity=Severity.ERROR,
       title="Все цифры и факты со слайда есть в исходных материалах")
def numbers_grounded(ctx: CheckContext) -> Iterable[Finding]:
    """Все цифры и факты со слайда есть в исходных материалах."""
    content = ctx.content
    if content is None:
        raise CheckUnavailable("контент-пакета нет: сверять числа не с чем")

    language = getattr(ctx.deck, "language", None) or "ru"
    if language != "ru":
        # Разбор чисел пока только для русского (change 7). Молчать нельзя:
        # непроверенные числа — не то же самое, что проверенные и верные.
        raise CheckUnavailable(f"разбор чисел для языка {language!r} не реализован")

    sources = content.all_numbers
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            text = block_text(block)
            if not text:
                continue
            for number in extract_numbers(text, language):
                if grounded_in(number, sources):
                    continue
                shown = number.raw or f"{number.value:g}"
                yield make_finding(
                    check_id="content.numbers_grounded",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=block_bbox(block, layout),
                    reason=f"number:{shown}",
                    message=(
                        f"Числа «{shown}» нет в исходных материалах: "
                        "либо оно выдумано, либо факт потерялся при разборе контента"
                    ),
                    evidence={
                        "raw": shown,
                        "value": f"{number.value:g}",
                        "unit": number.unit or "—",
                    },
                )
