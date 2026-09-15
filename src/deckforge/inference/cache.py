"""Кэш ответов модели по (skill@version, model, seed, hash(входа)). Change (8).

Нужен для воспроизводимости (C11) и для того, чтобы повторный прогон демо был быстрым.
"""

from __future__ import annotations

from pathlib import Path


class ResponseCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def key(self, *parts: str) -> str:
        raise NotImplementedError("change (8) inference-client")

    def get(self, key: str) -> str | None:
        raise NotImplementedError("change (8) inference-client")

    def put(self, key: str, value: str) -> None:
        raise NotImplementedError("change (8) inference-client")
