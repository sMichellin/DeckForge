"""Реестр моделей и валидация ограничений C1/C2 (лицензии и размер)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from deckforge.config import CONFIGS_DIR, load_yaml


class ModelSpec(BaseModel):
    hf_id: str
    license: str
    params_total_b: float = Field(gt=0)
    params_active_b: float | None = Field(default=None, gt=0)
    role: str
    endpoint_ref: str | None = None
    notes: str | None = None


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
    registry = ModelsRegistry.model_validate(load_yaml(path or CONFIGS_DIR / "models.yaml"))
    if strict and (violations := registry.violations()):
        raise ValueError("нарушения ограничений ТЗ:\n" + "\n".join(violations))
    return registry
