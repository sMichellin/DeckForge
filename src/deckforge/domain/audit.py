"""`AuditReport` — результат слоя audit (ARCHITECTURE.md §4.5)."""

from __future__ import annotations

from pydantic import Field

from deckforge.domain.base import BBox, DomainModel
from deckforge.domain.enums import AutoFix, Severity


class Finding(DomainModel):
    finding_id: str
    check_id: str = Field(description="Например layout.text_overflow")
    deterministic: bool
    severity: Severity
    slide_id: str | None = None
    block_id: str | None = None
    bbox_emu: BBox | None = None
    message: str
    auto_fix: AutoFix = AutoFix.NONE
    auto_fix_applied: bool = False
    model: str | None = Field(default=None, description="Для контекстуальных проверок")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: dict[str, str] = Field(default_factory=dict)


class Scores(DomainModel):
    content: float = Field(ge=0.0, le=5.0)
    design: float = Field(ge=0.0, le=5.0)
    coherence: float = Field(ge=0.0, le=5.0)


class AuditSummary(DomainModel):
    errors: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)
    infos: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    scores: Scores | None = None


class AuditReport(DomainModel):
    deck_id: str
    variant: str = Field(pattern=r"^[A-Z]$")
    findings: list[Finding] = Field(default_factory=list)
    summary: AuditSummary = Field(default_factory=AuditSummary)
    duration_s: float | None = Field(default=None, ge=0)

    def of_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def for_slide(self, slide_id: str) -> list[Finding]:
        return [f for f in self.findings if f.slide_id == slide_id]

    @property
    def has_errors(self) -> bool:
        return any(f.severity == Severity.ERROR for f in self.findings)


class CheckSpec(DomainModel):
    """Декларация проверки из `configs/audit_checks.yaml`."""

    check_id: str
    deterministic: bool
    severity: Severity
    title: str
    description: str = ""
    auto_fix: AutoFix = AutoFix.NONE
    enabled: bool = True
    params: dict[str, float | int | str | bool] = Field(default_factory=dict)
