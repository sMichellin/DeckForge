"""Проверки соответствия шаблону (§5.1). Change (15) `audit-deterministic`."""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, Severity


@check(id="template.font_not_in_theme", deterministic=True, severity=Severity.ERROR,
       title="Шрифт не из шаблона или гарнитур больше двух")
def font_not_in_theme(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="template.size_not_in_scale", deterministic=True, severity=Severity.WARNING,
       title="Кегль не из типографической шкалы шаблона")
def size_not_in_scale(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="template.color_not_in_palette", deterministic=True, severity=Severity.ERROR,
       auto_fix=AutoFix.MAP_TO_NEAREST_THEME_COLOR, title="Цвет не из палитры шаблона")
def color_not_in_palette(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="template.layout_not_from_template", deterministic=True, severity=Severity.ERROR,
       title="Слайд собран не на макете из шаблона")
def layout_not_from_template(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="template.decor_moved", deterministic=True, severity=Severity.WARNING,
       title="Логотип или колонтитул сдвинуты с положенного места")
def decor_moved(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(id="template.contrast_below_wcag", deterministic=True, severity=Severity.ERROR,
       title="Контраст текста к фону ниже 4.5:1")
def contrast_below_wcag(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")
