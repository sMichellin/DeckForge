"""Пороги профиля запуска доезжают до проверок. Запрос из #28, правка к change (17).

`configs/default.yaml` и `configs/profiles/*.yaml` объявляют `audit.vlm_votes`, а судья
читает его из `ctx.params`, куда приезжают только `params` из `configs/audit_checks.yaml`.
Значение в профиле лежало мёртвым: профиль `demo` просит одно голосование ради
предсказуемого времени на видео, а аудит всё равно шёл тремя — втрое дороже.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from deckforge.audit import deterministic as _deterministic  # noqa: F401  регистрация
from deckforge.audit.context import AuditContext
from deckforge.audit.registry import REGISTRY, RegisteredCheck
from deckforge.audit.runner import AuditRunner
from deckforge.config import CONFIGS_DIR, load_run_config
from deckforge.domain.audit import Finding
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import AutoFix, Severity, TextRole
from deckforge.domain.slide import DeckIR, FitResult, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.nodes.audit import PIPELINE_KEYS, check_params
from deckforge.registry import load_check_specs


@pytest.fixture
def deck(manifest: TemplateManifest) -> DeckIR:
    layout = manifest.layouts[1]
    step = next(s for s in manifest.typography_scale if s.role is TextRole.TITLE)
    slide = SlideIR(
        slide_id="s01",
        layout_id=layout.layout_id,
        variant="A",
        blocks=[
            TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Вывод")
        ],
        fit_report={"t": FitResult(final_size_pt=step.size_pt)},
    )
    return DeckIR(
        deck_id="d1",
        variant="A",
        template_id=manifest.template_id,
        seed=1,
        slides=[slide],
    )


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru")
    )


# --- разделение порогов и рычагов графа --------------------------------------


def test_graph_switches_do_not_leak_into_check_params() -> None:
    """`auto_fix` — решение графа, а не порог проверки: в `ctx.params` ему делать нечего."""
    params = check_params(
        {"run_semantic": True, "auto_fix": False, "max_fix_rounds": 2, "vlm_votes": 1}
    )
    assert params == {"vlm_votes": 1}


def test_every_pipeline_key_of_the_default_config_is_known() -> None:
    """Новый рычаг в `default.yaml` не должен молча уехать в пороги проверок."""
    audit = load_run_config().audit
    unknown = set(audit) - PIPELINE_KEYS - {"vlm_votes", "vlm_confidence_threshold"}
    assert unknown == set(), f"неизвестные ключи audit: {sorted(unknown)} — порог или рычаг?"


# --- пороги доезжают до проверки ---------------------------------------------


SPY_ID = "test.spy_params"


@pytest.fixture
def spy() -> Iterator[dict[str, Any]]:
    """Проверка, которая ничего не проверяет и только запоминает свои пороги.

    Реестр снимать регистрацию не умеет и не должен: проверка заводится один раз,
    при импорте модуля (change 15). Поэтому убираем запись руками — иначе подделка
    осталась бы в реестре и сломала `test_declared_checks_are_implemented`.
    """
    captured: dict[str, Any] = {}

    def fn(ctx: AuditContext) -> list[Finding]:  # type: ignore[arg-type]
        captured.update(ctx.params)
        return []

    REGISTRY.register(
        RegisteredCheck(
            check_id=SPY_ID,
            deterministic=True,
            severity=Severity.INFO,
            auto_fix=AutoFix.NONE,
            fn=fn,  # type: ignore[arg-type]
            title="подделка для замера порогов",
        )
    )
    try:
        yield captured
    finally:
        REGISTRY._checks.pop(SPY_ID, None)


async def params_seen_by(
    runner: AuditRunner,
    spy: dict[str, Any],
    deck: DeckIR,
    manifest: TemplateManifest,
    content: ContentPackage,
) -> dict[str, Any]:
    await runner.run(deck, manifest, content)
    return spy


async def test_run_params_reach_the_check(
    spy: dict[str, Any], deck: DeckIR, manifest: TemplateManifest, content: ContentPackage
) -> None:
    """`vlm_votes` не объявлен ни у одной проверки в YAML — без этого пути он не доедет."""
    runner = AuditRunner(enabled_checks=[SPY_ID], run_params={"vlm_votes": 1})
    assert (await params_seen_by(runner, spy, deck, manifest, content))["vlm_votes"] == 1


async def test_calibrated_check_threshold_beats_the_profile(
    spy: dict[str, Any], deck: DeckIR, manifest: TemplateManifest, content: ContentPackage
) -> None:
    """Порог, откалиброванный для проверки (#26), профиль молча не переопределяет."""
    runner = AuditRunner(
        enabled_checks=["density.too_many_bullets"], run_params={"max_bullets": 99}
    )
    report = await runner.run(deck, manifest, content)
    spec = load_check_specs().by_id("density.too_many_bullets")
    assert spec is not None and spec.params["max_bullets"] == 6
    assert report is not None

    runner = AuditRunner(enabled_checks=[SPY_ID], run_params={"max_bullets": 99})
    # У подделки своей записи в YAML нет, поэтому видно ровно то, что дал профиль.
    assert (await params_seen_by(runner, spy, deck, manifest, content))["max_bullets"] == 99


async def test_without_run_params_the_check_sees_only_its_own(
    spy: dict[str, Any], deck: DeckIR, manifest: TemplateManifest, content: ContentPackage
) -> None:
    runner = AuditRunner(enabled_checks=[SPY_ID])
    assert await params_seen_by(runner, spy, deck, manifest, content) == {}


# --- профили ------------------------------------------------------------------


@pytest.mark.parametrize(("profile", "votes"), [("demo", 1), ("final", 3)])
def test_profile_votes_are_not_dead_letters(profile: str, votes: int) -> None:
    """Ради чего всё и делалось: число голосований из профиля обязано доехать до судьи."""
    assert (CONFIGS_DIR / "profiles" / f"{profile}.yaml").exists()
    config = load_run_config(profile=profile)
    assert config.audit["vlm_votes"] == votes
    assert check_params(config.audit)["vlm_votes"] == votes
