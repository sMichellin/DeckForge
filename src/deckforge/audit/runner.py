"""Прогон аудита. Change (15)/(18).

Порядок по ADR-004: сначала детерминированные (дёшево, чинится автоматически),
затем VLM (дорого, чинится через HITL).
"""

from __future__ import annotations

from deckforge.domain.audit import AuditReport
from deckforge.domain.content import ContentPackage
from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest


class AuditRunner:
    def __init__(self, enabled_checks: list[str] | None = None) -> None:
        self.enabled_checks = enabled_checks

    async def run(
        self,
        deck: DeckIR,
        manifest: TemplateManifest,
        content: ContentPackage,
        previews: dict[str, bytes] | None = None,
    ) -> AuditReport:
        raise NotImplementedError("change (15) audit-deterministic")
