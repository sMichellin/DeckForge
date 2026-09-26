"""Имя макета — дополнительный голос за его вид. Change `layout-name-votes`, Т8
(`docs/agents/requirements-from-notes-26-09.md`).

Классификатор намеренно смотрел только на состав плейсхолдеров: имена произвольны, и опора
на них — заточка под знакомый шаблон (C6). Но на шаблонах кейса эвристика неуверенна там,
где имя однозначно: у VK Tech макеты «N_Контент» и «Свободный дизайн» (на нём 36 примеров
из 54) она зовёт титулом с уверенностью 0,60, а «Слайд "Спасибо!"» — «прочим». Отсюда
на превью содержательные слайды «на титульниках».

Решение владельца 26.09: имя **голосует**, состав **решает** при расхождении. Слова — в
`configs/layout_names.yaml`, не в коде. Имя меняет вид, только пока уверенность эвристики
ниже порога конфига; иначе остаётся вид по составу, а расхождение называет узел `parse`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from deckforge.config import CONFIGS_DIR, load_yaml
from deckforge.domain.enums import LayoutKind

VOCABULARY_PATH = CONFIGS_DIR / "layout_names.yaml"


@dataclass(frozen=True)
class NameVocabulary:
    """Основы слов по видам — в порядке проверки — и порог, ниже которого имя решает."""

    kinds: tuple[tuple[LayoutKind, tuple[str, ...]], ...]
    name_wins_below: float

    def kind_of(self, name: str) -> LayoutKind | None:
        """Вид по имени макета; `None` — имя ничего не говорит."""
        lowered = name.casefold()
        for kind, stems in self.kinds:
            if any(stem in lowered for stem in stems):
                return kind
        return None


def parse_vocabulary(raw: dict[str, object]) -> NameVocabulary:
    kinds_raw = raw.get("kinds") or {}
    assert isinstance(kinds_raw, dict), "layout_names.yaml: `kinds` — словарь видов"
    kinds = tuple(
        (LayoutKind(kind), tuple(str(stem).casefold() for stem in stems))
        for kind, stems in kinds_raw.items()
    )
    threshold = raw.get("name_wins_below", 0.7)
    wins = float(threshold) if isinstance(threshold, int | float) else 0.7
    return NameVocabulary(kinds=kinds, name_wins_below=wins)


@cache
def load_vocabulary(path: Path = VOCABULARY_PATH) -> NameVocabulary:
    """Словарь из конфига. Нет файла — пустой словарь: имена молчат, поведение прежнее."""
    if not path.is_file():
        return NameVocabulary(kinds=(), name_wins_below=0.0)
    return parse_vocabulary(load_yaml(path))


def name_mismatches(
    layouts: list[tuple[str, LayoutKind]], vocabulary: NameVocabulary
) -> list[tuple[str, LayoutKind, LayoutKind]]:
    """Макеты, у которых имя и итоговый вид разошлись: (имя, по имени, итоговый)."""
    out: list[tuple[str, LayoutKind, LayoutKind]] = []
    for name, kind in layouts:
        named = vocabulary.kind_of(name)
        if named is not None and named is not kind:
            out.append((name, named, kind))
    return out
