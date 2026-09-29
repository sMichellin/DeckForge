"""Судья и классификатор не размышляют. Change `the-judge-does-not-think` (план Б, круг 3, тимлид).

Замер 29.09 на стенде: разметка макетов VK Tech с размышлением — 1260 с и 3 отказа из 5
(`finish_reason=length`), без него — 13 с и 0 отказов. Все роли на локальном llama.cpp
идут без размышления.
"""

from __future__ import annotations

from deckforge.registry.models import CONFIGS_DIR, load_models_registry


def test_every_local_llama_role_has_thinking_off() -> None:
    """Норма: каждая роль на локальном сервере (`endpoint_ref: vlm`) — без размышления."""
    registry = load_models_registry(CONFIGS_DIR / "models.local.yaml")
    local = {name: spec for name, spec in registry.models.items() if spec.endpoint_ref == "vlm"}
    assert {"llm_fast", "vlm_judge"} <= set(local)
    thinking = [name for name, spec in local.items() if not spec.disable_thinking]
    assert thinking == [], f"размышляют: {thinking}"


def test_the_judge_asks_the_template_to_stop_thinking() -> None:
    """Норма: у `vlm_judge` флаг стоит (до 29.09 его не было, и разметка упиралась в бюджет)."""
    spec = load_models_registry(CONFIGS_DIR / "models.local.yaml").models["vlm_judge"]
    assert spec.disable_thinking is True
