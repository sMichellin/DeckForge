"""Сборка находок. Change (15) `audit-deterministic`.

Одно место, где рождается `Finding`, нужно ради двух свойств отчёта.

**Severity и авто-фикс не дублируются.** Они объявлены в `configs/audit_checks.yaml`
и попали в реестр при регистрации — проверка их не повторяет, иначе YAML перестал бы
быть источником истины и порог менялся бы в двух местах.

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
) -> Finding:
    """Находка с severity и авто-фиксом из реестра, а не из тела проверки."""
    registered = REGISTRY.get(check_id)
    return Finding(
        finding_id=finding_id(check_id, slide_id, block_id, reason or message),
        check_id=check_id,
        deterministic=registered.deterministic if registered else True,
        severity=registered.severity if registered else Severity.WARNING,
        auto_fix=registered.auto_fix if registered else AutoFix.NONE,
        slide_id=slide_id,
        block_id=block_id,
        bbox_emu=bbox,
        message=message,
        evidence=evidence or {},
    )
