"""Проверки вёрстки (§5.1). Change (15) `audit-deterministic`.

out_of_bounds, overlap, text_overflow, text_clipped, off_guides, margin_violation,
image_aspect_distorted.
"""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, Severity


@check(
    id="layout.out_of_bounds",
    deterministic=True,
    severity=Severity.ERROR,
    title="Элемент вышел за границы слайда",
)
def out_of_bounds(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(
    id="layout.overlap",
    deterministic=True,
    severity=Severity.ERROR,
    title="Два блока наложились друг на друга",
)
def overlap(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(
    id="layout.text_overflow",
    deterministic=True,
    severity=Severity.ERROR,
    auto_fix=AutoFix.SHRINK_FONT,
    title="Текст не помещается в свою рамку",
)
def text_overflow(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(
    id="layout.text_clipped",
    deterministic=True,
    severity=Severity.ERROR,
    title="Текст обрезан краем слайда",
)
def text_clipped(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(
    id="layout.off_guides",
    deterministic=True,
    severity=Severity.WARNING,
    auto_fix=AutoFix.SNAP_TO_GUIDE,
    title="Блоки не выровнены по направляющим макета",
)
def off_guides(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(
    id="layout.margin_violation",
    deterministic=True,
    severity=Severity.WARNING,
    title="Контент заходит в поля у краёв",
)
def margin_violation(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")


@check(
    id="layout.image_aspect_distorted",
    deterministic=True,
    severity=Severity.ERROR,
    title="Картинка растянута, пропорции нарушены",
)
def image_aspect_distorted(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (15) audit-deterministic")
