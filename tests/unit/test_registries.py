"""Реестры промптов, скиллов, моделей, вариантов и проверок (C9, C1, C2, C7)."""

from __future__ import annotations

import pytest

from deckforge.config import PROMPTS_DIR, load_run_config
from deckforge.registry import (
    get_prompt_registry,
    load_check_specs,
    load_models_registry,
    load_skill,
    load_variant_profiles,
)


def test_models_registry_satisfies_tz_constraints() -> None:
    """C1/C2: тот же гейт, что в CI (`scripts/check_licenses.py`)."""
    registry = load_models_registry(strict=False)
    assert registry.violations() == []
    assert set(registry.models) >= {"llm_main", "llm_fast", "vlm_judge"}


def test_every_model_license_is_open() -> None:
    registry = load_models_registry(strict=False)
    allowed = {lic.lower() for lic in registry.constraints.allowed_licenses}
    assert {s.license.lower() for s in registry.models.values()} <= allowed


def test_three_variant_profiles_are_distinct() -> None:
    """C7: три варианта различаются по объявленным осям, а не только по имени."""
    profiles = load_variant_profiles()
    assert set(profiles) == {"A", "B", "C"}
    assert len({p.density for p in profiles.values()}) == 3
    assert len({p.grouping for p in profiles.values()}) == 3
    assert len({p.data_visual for p in profiles.values()}) == 3
    assert all(p.rationale.strip() for p in profiles.values()), "ось различий надо обосновать"


def test_capacity_ratio_grows_with_density() -> None:
    profiles = load_variant_profiles()
    ratios = {p.density.value: p.capacity_ratio() for p in profiles.values()}
    assert ratios["low"] < ratios["medium"] < ratios["high"]


@pytest.mark.parametrize(
    "skill", ["deck_planner", "slide_composer", "headline_writer", "visual_selector", "audit_judge"]
)
def test_prompt_bundle_loads(skill: str) -> None:
    bundle = get_prompt_registry().load(skill)
    assert bundle.system_template.strip()
    assert bundle.user_template.strip()
    assert bundle.ref == f"{skill}@{bundle.version}"


def test_registry_pins_version_per_profile() -> None:
    registry = get_prompt_registry()
    assert registry.resolve_version("slide_composer", profile="dev") == "1.0.0"
    with pytest.raises(KeyError):
        registry.resolve_version("нет_такого_скилла")


def test_every_prompt_dir_is_declared_in_registry() -> None:
    """Промпт без записи в реестре невозможно версионировать — значит, его нет."""
    declared = set(get_prompt_registry().skills)
    on_disk = {p.name for p in PROMPTS_DIR.iterdir() if p.is_dir()}
    assert on_disk == declared


@pytest.mark.parametrize(
    "skill", ["template_analyst", "deck_architect", "slide_designer", "quality_auditor"]
)
def test_skill_spec_loads(skill: str) -> None:
    spec = load_skill(skill)
    assert spec.description.strip()
    assert spec.model_ref


def test_skill_prompt_refs_exist() -> None:
    prompts = set(get_prompt_registry().skills)
    for skill in ["deck_architect", "slide_designer", "quality_auditor"]:
        ref = load_skill(skill).prompt_ref
        assert ref in prompts, f"{skill} ссылается на несуществующий промпт {ref!r}"


def test_skill_model_refs_exist_in_models_registry() -> None:
    models = set(load_models_registry(strict=False).models)
    for skill in ["template_analyst", "deck_architect", "slide_designer", "quality_auditor"]:
        assert load_skill(skill).model_ref in models


def test_check_specs_cover_tz_appendix() -> None:
    specs = load_check_specs()
    ids = {c.check_id for c in specs.checks}
    # Приложение 1 ТЗ: вёрстка, шаблон, плотность, целостность
    assert len([i for i in ids if i.startswith("layout.")]) == 7
    assert len([i for i in ids if i.startswith("template.")]) == 6
    assert len([i for i in ids if i.startswith("density.")]) == 5
    # Семь: шесть из Приложения 1 плюс `integrity.content_lost` — потерю содержания
    # ТЗ отдельным вопросом не называет, но колода из одних заголовков ему не отвечает.
    assert len([i for i in ids if i.startswith("integrity.")]) == 7
    # 11 вопросов валидации контента
    assert len([i for i in ids if i.startswith("content.")]) == 11


def test_run_config_profiles_load() -> None:
    base = load_run_config()
    assert base.time_budget_s <= 300, "C5: бюджет колоды — не более 5 минут"
    dev = load_run_config("dev")
    assert dev.audit["run_semantic"] is False
    final = load_run_config("final")
    assert final.variants == ["A", "B", "C"]
    assert set(final.exports) == {"pptx", "pdf", "html"}
