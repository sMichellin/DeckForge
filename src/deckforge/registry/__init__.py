"""Реестры версионируемых артефактов: промпты, скиллы, модели, варианты, проверки (C9).

Прямое чтение файла промпта из кода запрещено — только через этот слой.
"""

from deckforge.registry.checks import CheckRegistryFile, load_check_specs
from deckforge.registry.models import ModelSpec, ModelsRegistry, load_models_registry
from deckforge.registry.prompts import PromptBundle, PromptRegistry, get_prompt_registry
from deckforge.registry.skills import SkillSpec, load_skill
from deckforge.registry.variants import load_variant_profiles

__all__ = [
    "CheckRegistryFile",
    "ModelSpec",
    "ModelsRegistry",
    "PromptBundle",
    "PromptRegistry",
    "SkillSpec",
    "get_prompt_registry",
    "load_check_specs",
    "load_models_registry",
    "load_skill",
    "load_variant_profiles",
]
