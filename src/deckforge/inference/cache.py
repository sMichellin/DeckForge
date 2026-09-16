"""Кэш ответов модели. Change (8) `inference-client`.

Нужен для двух вещей: воспроизводимости (C11 — тот же конфиг и seed дают тот же результат)
и живого демо, где повторный прогон не должен ждать инференс заново.

Ключ содержит версию промпта: правка промпта обязана инвалидировать кэш, иначе демо
покажет результат предыдущей версии.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CacheKey:
    model: str
    skill_ref: str
    seed: int | None
    payload_sha: str

    def as_path_name(self) -> str:
        seed = "noseed" if self.seed is None else str(self.seed)
        skill = self.skill_ref.replace("/", "_").replace("@", "_")
        return f"{skill}__{seed}__{self.payload_sha[:16]}.json"


class ResponseCache:
    """Файловый кэш. Содержимое — читаемый JSON: его полезно открыть глазами при разборе."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def key(
        self,
        *,
        model: str,
        skill_ref: str,
        seed: int | None,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any] | None = None,
    ) -> CacheKey:
        payload = json.dumps(
            {"messages": messages, "schema": response_schema},
            ensure_ascii=False,
            sort_keys=True,
        )
        return CacheKey(
            model=model,
            skill_ref=skill_ref,
            seed=seed,
            payload_sha=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )

    def _path(self, key: CacheKey) -> Path | None:
        if self.root is None:
            return None
        return self.root / key.model.replace("/", "_") / key.as_path_name()

    def get(self, key: CacheKey) -> str | None:
        path = self._path(key)
        if path is None or not path.exists():
            self.misses += 1
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Битый файл кэша — это не повод падать: просто спросим модель заново.
            self.misses += 1
            return None
        self.hits += 1
        text = payload.get("text")
        return text if isinstance(text, str) else None

    def put(self, key: CacheKey, text: str, meta: dict[str, Any] | None = None) -> None:
        path = self._path(key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"model": key.model, "skill": key.skill_ref, "seed": key.seed,
                 "text": text, "meta": meta or {}},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
