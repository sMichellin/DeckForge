"""Контекстуальные проверки (§5.2): VLM-судья по рендеру слайда. Change (18).

Снижение дисперсии: 3 прогона с разными seed, мажоритарное голосование, порог уверенности.
"""

from deckforge.audit.semantic import grounding, judge, spelling

__all__ = ["grounding", "judge", "spelling"]
