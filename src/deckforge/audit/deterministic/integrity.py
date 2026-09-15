"""Проверки целостности (§5.1). `integrity.slide_is_image` — машинная защита C3."""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import Severity


@check(id="integrity.file_opens", deterministic=True, severity=Severity.ERROR,
       title="Файл не открывается")
def file_opens(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="integrity.placeholder_text", deterministic=True, severity=Severity.ERROR,
       title="Остался текст-заглушка: lorem ipsum, XXX, TODO")
def placeholder_text(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="integrity.empty_slide", deterministic=True, severity=Severity.ERROR,
       title="Пустой слайд или слайд с одним заголовком")
def empty_slide(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="integrity.slide_is_image", deterministic=True, severity=Severity.ERROR,
       title="C3: слайд оказался картинкой, а не редактируемыми объектами")
def slide_is_image(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="integrity.chart_labels_missing", deterministic=True, severity=Severity.WARNING,
       title="У диаграммы нет подписей осей, единиц или легенды")
def chart_labels_missing(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="integrity.duplicate_slides", deterministic=True, severity=Severity.WARNING,
       title="Два слайда дублируют друг друга")
def duplicate_slides(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")
