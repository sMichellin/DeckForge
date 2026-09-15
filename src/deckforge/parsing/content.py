"""Контент-пакет → `ContentPackage`. Change (7) `content-ingestion`.

Числа извлекаются детерминированно и получают `fact_id` — якорь фактчекинга (§5.2).
"""

from __future__ import annotations

from pathlib import Path

from deckforge.domain.content import Brief, ContentPackage, Number


class ContentIngestor:
    def ingest(self, paths: list[Path], brief: Brief) -> ContentPackage:
        """markitdown → нормализованный markdown → факты, датасеты, ассеты."""
        raise NotImplementedError("change (7) content-ingestion")


def extract_numbers(text: str, language: str = "ru") -> list[Number]:
    """«37,5 %», «1 200 млн ₽», «x2.3» → нормализованные `Number` с сохранением `raw`."""
    raise NotImplementedError("change (7) content-ingestion")
