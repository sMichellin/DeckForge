"""Конфиги скиллов воркфлоу: `skills/<skill>/<version>/skill.yaml` (C9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from deckforge.config import SKILLS_DIR, load_yaml


class SkillSpec(BaseModel):
    """Декларация шага воркфлоу: какой промпт, какая модель, какие деградации."""

    name: str
    version: str
    description: str = ""
    prompt_ref: str | None = Field(default=None, description="Имя скилла в prompts/registry.yaml")
    model_ref: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    retries: int = Field(default=2, ge=0)
    fallback: str | None = Field(default=None, description="Цепочка деградации (§15)")
    params: dict[str, Any] = Field(default_factory=dict)


def load_skill(name: str, version: str | None = None, root: Path | None = None) -> SkillSpec:
    root = root or SKILLS_DIR
    registry = load_yaml(root / "registry.yaml").get("skills") or {}
    version = version or registry.get(name, {}).get("active")
    if version is None:
        raise KeyError(f"скилл {name!r} не объявлен в skills/registry.yaml")
    data = load_yaml(root / name / version / "skill.yaml")
    return SkillSpec.model_validate({"name": name, "version": version, **data})
