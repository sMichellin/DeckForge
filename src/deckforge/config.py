"""Конфигурация запуска (C11): только из `configs/*.yaml` и переменных окружения."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS_DIR = REPO_ROOT / "configs"
PROMPTS_DIR = REPO_ROOT / "prompts"
SKILLS_DIR = REPO_ROOT / "skills"
ASSETS_DIR = REPO_ROOT / "assets"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"


class Settings(BaseSettings):
    """Секреты и эндпоинты — только из окружения, никогда из YAML в git."""

    model_config = SettingsConfigDict(
        env_prefix="DECKFORGE_", env_file=".env", extra="ignore", frozen=True
    )

    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "changeme"
    vlm_base_url: str = "http://localhost:8001/v1"
    vlm_api_key: str = "changeme"
    t2i_base_url: str = "http://localhost:8002/v1"
    t2i_api_key: str = "changeme"

    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "deckforge"
    languagetool_url: str = "http://localhost:8010"

    soffice_bin: str = "soffice"
    #: Какой реестр моделей брать. Провайдер меняется правкой этой переменной
    #: и base_url — код моделей по имени не знает (C11).
    models_config: str = "models.yaml"
    artifacts_dir: Path = ARTIFACTS_DIR
    profile: str = "dev"


class RunConfig(BaseModel):
    """Содержимое `configs/default.yaml` — воспроизводимый запуск конфиг-файлом."""

    seed: int = 1337
    language: str = "ru"
    target_slides: int = 12
    variants: list[str] = Field(default_factory=lambda: ["A", "B", "C"])
    exports: list[str] = Field(default_factory=lambda: ["pptx", "pdf", "html"])
    time_budget_s: int = 300
    parallel_slides: int = 6
    audit: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: ожидался YAML-объект")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_run_config(profile: str | None = None, config_path: Path | None = None) -> RunConfig:
    """`default.yaml` + `profiles/<profile>.yaml`. Профиль переопределяет базу."""
    base = load_yaml(config_path or CONFIGS_DIR / "default.yaml")
    if profile:
        profile_path = CONFIGS_DIR / "profiles" / f"{profile}.yaml"
        if profile_path.exists():
            base = _deep_merge(base, load_yaml(profile_path))
    return RunConfig.model_validate(base)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
