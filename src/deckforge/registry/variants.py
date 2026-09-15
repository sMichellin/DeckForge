"""Загрузка трёх профилей вёрстки из `configs/variants.yaml` (C7)."""

from __future__ import annotations

from pathlib import Path

from deckforge.config import CONFIGS_DIR, load_yaml
from deckforge.domain.variants import VariantProfile


def load_variant_profiles(path: Path | None = None) -> dict[str, VariantProfile]:
    raw = load_yaml(path or CONFIGS_DIR / "variants.yaml").get("variants") or {}
    return {
        vid: VariantProfile.model_validate({"variant_id": vid, **spec})
        for vid, spec in raw.items()
    }
