"""Реестр проверок: декоратор регистрирует, YAML объявляет, одно не расходится с другим."""

from __future__ import annotations

import pytest

from deckforge.audit import REGISTRY, CheckRegistry, check
from deckforge.audit import deterministic as _deterministic  # регистрация проверок
from deckforge.audit import semantic as _semantic  # регистрация проверок
from deckforge.domain.audit import Severity
from deckforge.registry import load_check_specs

_ = (_deterministic, _semantic)


def test_decorator_registers_check() -> None:
    registry = CheckRegistry()
    from deckforge.audit import registry as registry_module

    original, registry_module.REGISTRY = registry_module.REGISTRY, registry
    try:

        @check(id="test.sample", deterministic=True, severity=Severity.ERROR, title="Проба")
        def sample(ctx: object) -> list[object]:
            return []

        assert "test.sample" in registry
        assert registry.get("test.sample").severity is Severity.ERROR
        with pytest.raises(ValueError, match="уже зарегистрирована"):
            registry.register(registry.get("test.sample"))
    finally:
        registry_module.REGISTRY = original


def test_declared_checks_are_implemented() -> None:
    """YAML объявляет проверку → в коде обязан быть @check с тем же id."""
    declared = {c.check_id for c in load_check_specs().checks}
    implemented = {c.check_id for c in REGISTRY.all()}
    assert declared - implemented == set(), "объявлены, но не реализованы"
    assert implemented - declared == set(), "реализованы, но не объявлены в audit_checks.yaml"


def test_determinism_flag_matches_yaml() -> None:
    specs = {c.check_id: c for c in load_check_specs().checks}
    for item in REGISTRY.all():
        assert item.deterministic == specs[item.check_id].deterministic, item.check_id


def test_deterministic_checks_dominate() -> None:
    """ADR-004: детерминированных проверок должно быть больше — они дешевле и стабильнее."""
    assert len(REGISTRY.deterministic()) > len(REGISTRY.semantic())


def test_c3_check_is_present_and_is_an_error() -> None:
    item = REGISTRY.get("integrity.slide_is_image")
    assert item is not None and item.severity is Severity.ERROR
