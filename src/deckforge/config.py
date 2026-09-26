"""Конфигурация запуска (C11): только из `configs/*.yaml` и переменных окружения."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Бюджет стадии разбора шаблона из §12 ТЗ. Продублирован здесь числом намеренно:
#: `config` лежит ниже `pipeline`, откуда берётся расписание бюджета, и импорт «вверх»
#: запрещён (ARCHITECTURE.md §3). Расхождение сторожит тест.
STAGE_PARSE_BUDGET_S = 25

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
    languagetool_url: str = "http://localhost:8010"

    soffice_bin: str = "soffice"
    #: Кегль, ниже которого текст на слайде перестаёт читаться с расстояния (RG35).
    #: Умолчание живёт в `layout/by_design.READING_FLOOR_PT`; здесь — способ задать его
    #: снаружи, не правя код: порог приёмки зависит от того, с какого расстояния колоду
    #: смотрят, и константой в коде быть не должен.
    reading_floor_pt: float | None = None
    #: Предел времени на разметку макетов моделью, секунды. Разметку делает VLM через
    #: общий однослотовый сервер, очередь к нему ничем не ограничена: прогон
    #: `aa5eca9aa135` разбирал незнакомый шаблон 2375 с при бюджете стадии 25 с (§12).
    #: Кончился предел — остальные макеты размечает эвристика. Ноль снимает предел:
    #: так работает предразбор при деплое, которому спешить некуда.
    layout_vlm_budget_s: float = float(STAGE_PARSE_BUDGET_S)
    #: Какой реестр моделей брать. Провайдер меняется правкой этой переменной
    #: и base_url — код моделей по имени не знает (C11).
    models_config: str = "models.yaml"
    artifacts_dir: Path = ARTIFACTS_DIR
    #: Профиль **закрепления версий промптов** (`prompts/registry.yaml`, раздел `pinned`),
    #: а не набор настроек прогона — тот приходит запросом и лежит в `configs/profiles/`.
    #: Имена у них пересекаются, и это уже стоило дорого.
    #:
    #: `None` — брать `active`, то есть ту версию, которую репозиторий считает текущей.
    #: Раньше здесь стояло `"dev"`, и поскольку `slide_composer` закреплён для `dev`
    #: на `1.0.0`, **каждый прогон через API и CLI шёл на промпте `1.0.0`**, а не на
    #: активном. Обнаружено на прогонах RG20 (24.09): провенанс слайдов показал
    #: `slide_composer@1.0.0` при активной `1.4.0`, и правка RG4 на стенде просто
    #: не работала. Закрепление — осознанный выбор, и делаться он должен явно:
    #: `DECKFORGE_PROFILE=dev`.
    profile: str | None = None


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


def available_profiles() -> list[str]:
    """Имена профилей, которые лежат в `configs/profiles/`.

    Список берётся с диска, а не из кода: профиль — это файл (C11), и знать их
    наперечень не должен ни API, ни интерфейс. Добавили `configs/profiles/<имя>.yaml` —
    он сразу доступен, без правки кода.
    """
    directory = CONFIGS_DIR / "profiles"
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.yaml"))


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
