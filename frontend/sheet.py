"""Лист колоды: слайды прогона рядом с примерами шаблона. Change `the-deck-sheet`,
план Б, шаг 6 (#245).

Разбор 28.09 шёл глазами по PDF, а выбор примера — строкой текста «почему такие слайды».
Что `ex018` стоит на шести слайдах VK Tech из десяти и что у него пустые карточки, из текста
не видно. Лист собирается из `run.json` и превью, без модели и без рендера: картинки
отдаёт сервис, а здесь — только строки листа и предупреждения, проверенные тестами.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

#: Больше скольких слайдов на одном примере — повтор (план Б, строка 2: «≤ 2, не подряд»).
MAX_USES = 2
#: Пустая карточка примера на слайде — находка аудита (план Б, строка 3, RG63).
EMPTY_GROUP = "integrity.empty_group"


@dataclass(frozen=True, slots=True)
class SheetRow:
    """Строка листа: слайд, по чему он собран и что на нём нашёл аудит."""

    slide_id: str
    recipe_id: str | None
    layout_id: str | None
    why: str
    uses: int
    total: int
    empty_groups: int

    @property
    def caption(self) -> str:
        if self.recipe_id is None:
            source = f"по макету {self.layout_id}" if self.layout_id else "по макету"
        else:
            source = f"{self.recipe_id} — на {_slides(self.uses)} из {self.total}"
        parts = [f"**{self.slide_id}** · {source}"]
        if self.empty_groups:
            parts.append(f"пустых карточек: {self.empty_groups}")
        return " · ".join(parts)


def _slides(count: int) -> str:
    """«1 слайде», «2 слайдах», «11 слайдах», «21 слайде»."""
    one = count % 10 == 1 and count % 100 != 11
    return f"{count} слайде" if one else f"{count} слайдах"


def sheet_rows(report: dict[str, Any]) -> list[SheetRow]:
    """Строки листа в порядке колоды — по `slide_choices` отчёта прогона (Т7)."""
    choices = [c for c in report.get("slide_choices") or [] if c.get("slide_id")]
    uses = Counter(c.get("recipe_id") for c in choices if c.get("recipe_id"))
    empty = Counter(
        f.get("slide_id")
        for f in report.get("findings_detail") or []
        if f.get("check_id") == EMPTY_GROUP
    )
    return [
        SheetRow(
            slide_id=str(c["slide_id"]),
            recipe_id=c.get("recipe_id") or None,
            layout_id=c.get("layout_id") or None,
            why=str(c.get("why") or ""),
            uses=uses.get(c.get("recipe_id"), 0),
            total=len(choices),
            empty_groups=empty.get(c["slide_id"], 0),
        )
        for c in choices
    ]


def repeat_warnings(rows: list[SheetRow], max_uses: int = MAX_USES) -> list[str]:
    """Примеры, стоящие больше чем на `max_uses` слайдах или на двух соседних."""
    warnings: list[str] = []
    by_recipe: dict[str, list[str]] = {}
    for row in rows:
        if row.recipe_id:
            by_recipe.setdefault(row.recipe_id, []).append(row.slide_id)
    for recipe_id, slides in by_recipe.items():
        if len(slides) > max_uses:
            warnings.append(
                f"{recipe_id} — на {len(slides)} слайдах из {len(rows)}: {', '.join(slides)}"
            )
    for left, right in pairwise(rows):
        if left.recipe_id and left.recipe_id == right.recipe_id:
            warnings.append(f"{left.recipe_id} — на соседних {left.slide_id} и {right.slide_id}")
    return warnings
