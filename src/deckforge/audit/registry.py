"""Реестр проверок аудита. Change (15) `audit-deterministic`.

Добавление проверки = один файл с `@check(...)` + запись в `configs/audit_checks.yaml`.
Пайплайн при этом не меняется (ARCHITECTURE.md §5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, Severity


class CheckContext(Protocol):
    """Всё, что доступно проверке. Детерминированные используют только IR и манифест."""

    @property
    def manifest(self) -> Any: ...
    @property
    def deck(self) -> Any: ...
    @property
    def content(self) -> Any: ...
    @property
    def previews(self) -> dict[str, bytes]: ...
    @property
    def params(self) -> dict[str, Any]: ...


CheckFn = Callable[[CheckContext], Iterable[Finding]]


@dataclass(frozen=True, slots=True)
class RegisteredCheck:
    check_id: str
    deterministic: bool
    severity: Severity
    auto_fix: AutoFix
    fn: CheckFn
    title: str


class CheckRegistry:
    def __init__(self) -> None:
        self._checks: dict[str, RegisteredCheck] = {}

    def register(self, check: RegisteredCheck) -> None:
        if check.check_id in self._checks:
            raise ValueError(f"проверка {check.check_id!r} уже зарегистрирована")
        self._checks[check.check_id] = check

    def get(self, check_id: str) -> RegisteredCheck | None:
        return self._checks.get(check_id)

    def all(self) -> list[RegisteredCheck]:
        return sorted(self._checks.values(), key=lambda c: c.check_id)

    def deterministic(self) -> list[RegisteredCheck]:
        return [c for c in self.all() if c.deterministic]

    def semantic(self) -> list[RegisteredCheck]:
        return [c for c in self.all() if not c.deterministic]

    def __len__(self) -> int:
        return len(self._checks)

    def __contains__(self, check_id: object) -> bool:
        return check_id in self._checks


REGISTRY = CheckRegistry()


def _title_from_doc(fn: CheckFn) -> str:
    doc = (fn.__doc__ or "").strip()
    return doc.splitlines()[0] if doc else ""


def check(
    *,
    id: str,
    deterministic: bool,
    severity: Severity = Severity.WARNING,
    auto_fix: AutoFix = AutoFix.NONE,
    title: str = "",
) -> Callable[[CheckFn], CheckFn]:
    """Декоратор регистрации проверки.

    Каждая проверка обязана иметь тест на слайде-нарушителе **и** на слайде-норме
    (правило агента №6, ARCHITECTURE.md §7.4).
    """

    def decorator(fn: CheckFn) -> CheckFn:
        REGISTRY.register(
            RegisteredCheck(
                check_id=id,
                deterministic=deterministic,
                severity=severity,
                auto_fix=auto_fix,
                fn=fn,
                title=title or _title_from_doc(fn) or id,
            )
        )
        return fn

    return decorator
