"""Сборка клиентов по реестру моделей. Change (8) `inference-client`.

Роль модели (`llm_main`, `vlm_judge`, …) объявлена в `configs/models.yaml`, эндпоинт —
в окружении. Код нигде не называет конкретную модель: смена провайдера — это правка
одного YAML и одной переменной окружения, а не правка кода (C11).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from deckforge.config import Settings, get_settings
from deckforge.inference.cache import ResponseCache
from deckforge.inference.client import InferenceClient
from deckforge.inference.vlm import VlmJudge
from deckforge.registry.models import ModelsRegistry, load_models_registry


@lru_cache(maxsize=1)
def _registry() -> ModelsRegistry:
    # strict=True: нарушение C1/C2 обязано падать при старте, а не всплыть на защите.
    return load_models_registry(strict=True)


def client_for(role: str, settings: Settings | None = None) -> InferenceClient:
    registry = _registry()
    spec = registry.models.get(role)
    if spec is None:
        known = ", ".join(sorted(registry.models))
        raise KeyError(f"роль модели {role!r} не объявлена в models.yaml (есть: {known})")
    return InferenceClient(spec=spec, settings=settings or get_settings())


def response_cache(settings: Settings | None = None) -> ResponseCache:
    settings = settings or get_settings()
    return ResponseCache(root=Path(settings.artifacts_dir) / "inference-cache")


def vlm_judge(
    role: str = "vlm_judge", settings: Settings | None = None, *, use_cache: bool = True
) -> VlmJudge:
    return VlmJudge(
        client_for(role, settings),
        cache=response_cache(settings) if use_cache else None,
        skill_ref=role,
    )
