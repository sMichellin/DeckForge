"""Загрузка деклараций проверок аудита из `configs/audit_checks.yaml` (§5)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from deckforge.config import CONFIGS_DIR, load_yaml
from deckforge.domain.audit import CheckSpec


class CheckRegistryFile(BaseModel):
    checks: list[CheckSpec]

    def by_id(self, check_id: str) -> CheckSpec | None:
        return next((c for c in self.checks if c.check_id == check_id), None)

    @property
    def enabled(self) -> list[CheckSpec]:
        return [c for c in self.checks if c.enabled]


def load_check_specs(path: Path | None = None) -> CheckRegistryFile:
    raw = load_yaml(path or CONFIGS_DIR / "audit_checks.yaml")
    return CheckRegistryFile.model_validate(
        {"checks": [{"check_id": cid, **spec} for cid, spec in (raw.get("checks") or {}).items()]}
    )
