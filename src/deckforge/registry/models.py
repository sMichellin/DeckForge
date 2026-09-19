"""Реестр моделей и валидация ограничений C1/C2 (лицензии и размер)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from deckforge.config import CONFIGS_DIR, get_settings, load_yaml


class ModelSpec(BaseModel):
    hf_id: str
    license: str
    params_total_b: float = Field(gt=0)
    params_active_b: float | None = Field(default=None, gt=0)
    role: str
    endpoint_ref: str | None = None
    provider: str | None = Field(
        default=None,
        description=(
            "Провайдер инференса. Для роутера HuggingFace это часть идентификатора "
            "(`модель:провайдер`). Пин обязателен там, где провайдеры одной модели "
            "отличаются по возможностям: у Qwen3.8-27B structured output есть "
            "у deepinfra и ovhcloud и нет у novita."
        ),
    )
    supports_structured_output: bool = Field(
        default=True,
        description="Держит ли бэкенд JSON Schema. Если нет, схема уходит в текст промпта.",
    )
    supports_schema_patterns: bool = Field(
        default=True,
        description=(
            "Переваривает ли бэкенд `pattern` внутри схемы. llama.cpp переводит JSON Schema "
            "в GBNF-грамматику и на регулярном выражении вида `^s\\d{2,}$` отвечает "
            "`400 failed to parse grammar` — отвергая запрос целиком. Замер 18.09: та же "
            "схема без `pattern` собирается. Выключать structured output ради этого не нужно: "
            "довольно не слать одно поле."
        ),
    )
    timeout_s: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Сколько ждать ответа на один вызов, секунд. Не задано — общий таймаут клиента. "
            "Нужен медленным бэкендам: план с бюджетом 8192 токена на llama.cpp при ~38 ток/с "
            "генерируется до 215 с, а под нагрузкой дольше, и таймаут 120 с обрывал его "
            "на каждой попытке (прогон 19.09, `APITimeoutError` на стадии plan)."
        ),
    )
    disable_thinking: bool = Field(
        default=False,
        description=(
            "Просить бэкенд не размышлять: `chat_template_kwargs.enable_thinking=false` "
            "(llama.cpp, vLLM с шаблоном Qwen3). Команда `/no_think` в тексте промпта "
            "на локальной сборке не действует — замер 20.09: 11,6 тыс. знаков размышления "
            "против 21 тыс. и 270 с плана против 203. Параметр шаблона — 0 знаков."
        ),
    )
    max_concurrency: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Сколько запросов бэкенд обслуживает одновременно. Не задано — без ограничения "
            "со стороны модели. У llama.cpp с одним слотом лишние запросы стоят в очереди, "
            "и ожидание входит в таймаут: прогон 19.09 слал 6 слайдов разом, и последние "
            "три не дождались ответа за 300 с."
        ),
    )
    notes: str | None = None

    @property
    def endpoint_model_id(self) -> str:
        """Идентификатор, который уходит в запрос."""
        return f"{self.hf_id}:{self.provider}" if self.provider else self.hf_id


class ModelConstraints(BaseModel):
    allowed_licenses: list[str]
    max_params_b_llm: float
    max_params_b_t2i: float


class ModelsRegistry(BaseModel):
    models: dict[str, ModelSpec]
    constraints: ModelConstraints

    def violations(self) -> list[str]:
        """C1/C2. Тот же список печатает `scripts/check_licenses.py` в CI."""
        out: list[str] = []
        allowed = {lic.lower() for lic in self.constraints.allowed_licenses}
        for name, spec in self.models.items():
            if spec.license.lower() not in allowed:
                out.append(f"{name} ({spec.hf_id}): лицензия {spec.license} не входит в {allowed}")
            limit = (
                self.constraints.max_params_b_t2i
                if "t2i" in name or "image" in spec.role
                else self.constraints.max_params_b_llm
            )
            if spec.params_total_b > limit:
                out.append(
                    f"{name} ({spec.hf_id}): {spec.params_total_b}B превышает лимит {limit}B"
                )
        return out


def load_models_registry(path: Path | None = None, *, strict: bool = True) -> ModelsRegistry:
    """`strict=True` — отказ на нарушении C1/C2. `strict=False` — для отчёта в CI."""
    path = path or CONFIGS_DIR / get_settings().models_config
    registry = ModelsRegistry.model_validate(load_yaml(path))
    if strict and (violations := registry.violations()):
        raise ValueError("нарушения ограничений ТЗ:\n" + "\n".join(violations))
    return registry
