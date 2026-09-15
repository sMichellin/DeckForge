"""`content.numbers_grounded` — фактчекинг чисел. Change (18) `audit-semantic`.

Не «на глаз»: числа извлекаются из `SlideIR` детерминированно и сверяются с
`ContentPackage.facts[].numbers`. Модель привлекается только к форматным расхождениям
(«37 %» против «0.37»).
"""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import Severity


@check(id="content.numbers_grounded", deterministic=False, severity=Severity.ERROR,
       title="Все цифры и факты со слайда есть в исходных материалах")
def numbers_grounded(ctx: CheckContext) -> Iterable[Finding]:
    raise NotImplementedError("change (18) audit-semantic")
