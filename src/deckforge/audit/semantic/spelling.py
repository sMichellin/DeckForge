"""`content.no_typos` — LanguageTool, а не модель: орфография детерминируема (§5.2)."""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import Severity


@check(id="content.no_typos", deterministic=True, severity=Severity.WARNING,
       title="Текст без опечаток")
def no_typos(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (18) audit-semantic")
