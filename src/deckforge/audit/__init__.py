"""Слой `audit`: детерминированные проверки, VLM-судья, авто-фиксы (ADR-004).

Changes: (15) audit-deterministic, (18) audit-semantic, (19) audit-remediation.
Аудит никогда не меняет слайд молча — любое изменение записывается в `Finding`.
"""

from deckforge.audit.registry import REGISTRY, CheckRegistry, check
from deckforge.audit.runner import AuditRunner

__all__ = ["REGISTRY", "AuditRunner", "CheckRegistry", "check"]
