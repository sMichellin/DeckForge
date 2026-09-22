"""Сборка находок. Change (15) `audit-deterministic`.

Одно место, где рождается `Finding`, нужно ради двух свойств отчёта.

**Severity и авто-фикс не дублируются.** Они объявлены в `configs/audit_checks.yaml`
и попали в реестр при регистрации — проверка их не повторяет, иначе YAML перестал бы
быть источником истины и порог менялся бы в двух местах. Исключение одно — находка
**мягче** объявленной: проверка знает, что нарушения нет, а есть замечание
(подпись прошла минимум контраста, но без запаса, change `one-contrast-rule`).
Строже реестра находка не бывает: ошибку объявляет YAML, а не тело проверки.

**`finding_id` устойчив.** Это хеш от того, на что проверка указывает, а не счётчик.
Два прогона на одном файле дают одинаковые идентификаторы, поэтому интерфейс помнит,
что пользователь уже отклонил, а тесты сравнивают отчёты целиком.
"""

from __future__ import annotations

import hashlib

from deckforge.audit.registry import REGISTRY
from deckforge.domain.audit import Finding
from deckforge.domain.base import BBox
from deckforge.domain.enums import AutoFix, Severity

_ID_LENGTH = 12


def finding_id(check_id: str, slide_id: str | None, block_id: str | None, reason: str) -> str:
    raw = "|".join((check_id, slide_id or "-", block_id or "-", reason))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:_ID_LENGTH]


def make_finding(
    *,
    check_id: str,
    message: str,
    slide_id: str | None = None,
    block_id: str | None = None,
    bbox: BBox | None = None,
    reason: str = "",
    evidence: dict[str, str] | None = None,
    severity: Severity | None = None,
) -> Finding:
    """Находка с severity и авто-фиксом из реестра, а не из тела проверки.

    `severity` — только понижение: `info` у проверки уровня `error`. Попытка поднять
    уровень выше объявленного игнорируется, чтобы YAML оставался потолком.
    """
    registered = REGISTRY.get(check_id)
    declared = registered.severity if registered else Severity.WARNING
    return Finding(
        finding_id=finding_id(check_id, slide_id, block_id, reason or message),
        check_id=check_id,
        deterministic=registered.deterministic if registered else True,
        severity=_softer(declared, severity),
        auto_fix=registered.auto_fix if registered else AutoFix.NONE,
        slide_id=slide_id,
        block_id=block_id,
        bbox_emu=bbox,
        message=message,
        evidence=evidence or {},
    )


_WEIGHT = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


def _softer(declared: Severity, requested: Severity | None) -> Severity:
    if requested is None:
        return declared
    return requested if _WEIGHT[requested] < _WEIGHT[declared] else declared
