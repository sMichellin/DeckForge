"""Авто-фиксы (§5.3). Change (19) `audit-remediation`.

Фикс никогда не применяется молча: он пишется в finding как `auto_fix_applied: true`
и показывается в UI. Выбор, что чинить, делает человек (HITL-узел графа).
"""

from deckforge.audit.fixes.apply import FixApplier

__all__ = ["FixApplier"]
