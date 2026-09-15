"""Загрузка промптов по семверсии (C9, ARCHITECTURE.md §9.1).

Раскладка: `prompts/<skill>/<semver>/{system.j2,user.j2,schema.json,meta.yaml}`.
Активная версия для профиля берётся из `prompts/registry.yaml`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, Field

from deckforge.config import PROMPTS_DIR, load_yaml


class PromptMeta(BaseModel):
    skill: str
    version: str
    model_ref: str
    response_model: str | None = Field(
        default=None,
        description="Путь к Pydantic-модели ответа, например deckforge.domain.plan.DeckPlan",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    author: str | None = None
    changelog: str | None = None


class PromptBundle(BaseModel):
    """Промпт целиком: шаблоны, схема ответа, параметры вызова."""

    skill: str
    version: str
    meta: PromptMeta
    system_template: str
    user_template: str
    response_schema: dict[str, Any] | None = None

    @property
    def ref(self) -> str:
        """`skill@version` — попадает в трейс и в `SlideIR.provenance.prompt_version`."""
        return f"{self.skill}@{self.version}"

    def render(self, **context: Any) -> tuple[str, str]:
        env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True)
        system = env.from_string(self.system_template).render(**context)
        user = env.from_string(self.user_template).render(**context)
        return system, user


class SkillEntry(BaseModel):
    active: str
    pinned: dict[str, str] = Field(default_factory=dict)
    model_ref: str


class PromptRegistry(BaseModel):
    root: Path
    skills: dict[str, SkillEntry]

    model_config = {"arbitrary_types_allowed": True}

    def resolve_version(self, skill: str, profile: str | None = None) -> str:
        entry = self.skills.get(skill)
        if entry is None:
            raise KeyError(f"скилл {skill!r} не объявлен в prompts/registry.yaml")
        if profile and profile in entry.pinned:
            return entry.pinned[profile]
        return entry.active

    def load(self, skill: str, profile: str | None = None, version: str | None = None
             ) -> PromptBundle:
        version = version or self.resolve_version(skill, profile)
        base = self.root / skill / version
        if not base.is_dir():
            raise FileNotFoundError(f"нет каталога промпта: {base}")
        meta = PromptMeta.model_validate(
            {"skill": skill, "version": version, **load_yaml(base / "meta.yaml")}
        )
        schema_path = base / "schema.json"
        return PromptBundle(
            skill=skill,
            version=version,
            meta=meta,
            system_template=(base / "system.j2").read_text(encoding="utf-8"),
            user_template=(base / "user.j2").read_text(encoding="utf-8"),
            response_schema=(
                json.loads(schema_path.read_text(encoding="utf-8"))
                if schema_path.exists()
                else None
            ),
        )

    def available_versions(self, skill: str) -> list[str]:
        base = self.root / skill
        return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


@lru_cache(maxsize=1)
def get_prompt_registry(root: Path | None = None) -> PromptRegistry:
    root = root or PROMPTS_DIR
    raw = load_yaml(root / "registry.yaml")
    skills = {name: SkillEntry.model_validate(v) for name, v in (raw.get("skills") or {}).items()}
    return PromptRegistry(root=root, skills=skills)
