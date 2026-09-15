"""Применение выбранных пользователем фиксов к `SlideIR`. Change (19)."""

from __future__ import annotations

from deckforge.domain.audit import AuditReport, Finding
from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest


class FixApplier:
    def apply(
        self,
        deck: DeckIR,
        findings: list[Finding],
        manifest: TemplateManifest,
    ) -> tuple[DeckIR, AuditReport]:
        """Возвращает обновлённую колоду и отчёт, где у применённых фиксов стоит флаг."""
        raise NotImplementedError("change (19) audit-remediation")
