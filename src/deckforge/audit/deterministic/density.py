"""Проверки плотности (§5.1). Пороги — из `configs/audit_checks.yaml`, не из кода."""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, Severity


@check(id="density.too_many_bullets", deterministic=True, severity=Severity.WARNING,
       auto_fix=AutoFix.SPLIT_SLIDE, title="Больше 6 буллетов на слайде")
def too_many_bullets(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="density.bullet_too_long", deterministic=True, severity=Severity.WARNING,
       auto_fix=AutoFix.SHORTEN_TEXT, title="Буллет длиннее 15 слов")
def bullet_too_long(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="density.table_too_big", deterministic=True, severity=Severity.WARNING,
       title="Таблица больше 7 строк или 5 колонок")
def table_too_big(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="density.too_many_series", deterministic=True, severity=Severity.WARNING,
       title="Больше 5 серий на диаграмме")
def too_many_series(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="density.fill_ratio", deterministic=True, severity=Severity.WARNING,
       title="Слайд заполнен меньше четверти или больше трёх четвертей")
def fill_ratio(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")
