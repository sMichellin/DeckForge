"""Путь сборки слайда задаётся конфигом. Change `the-example-comes-before-the-text` (ADR-009).

План Б переставляет шаги: пример выбирается до текста. Новый путь вводится за флагом
`composition.path`, и до приёмки старый путь остаётся базой для сравнения. Поэтому флаг
обязан быть строгим: опечатка — ошибка, а `by_example` без узла `assign` — отказ, а не
молчаливый `legacy`. Иначе приёмка сравнила бы старый путь со старым.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from deckforge import config
from deckforge.config import RunConfig, load_run_config
from deckforge.domain.content import Brief
from deckforge.pipeline.deps import Deps, PipelineError
from deckforge.pipeline.run import RunResult, ensure_composition_path, generate_variant


def _configs(root: Path, default: str, profiles: dict[str, str] | None = None) -> Path:
    """Каталог конфигов, как `configs/`: `default.yaml` и `profiles/<имя>.yaml`."""
    (root / "profiles").mkdir(parents=True)
    (root / "default.yaml").write_text(default, encoding="utf-8")
    for name, text in (profiles or {}).items():
        (root / "profiles" / f"{name}.yaml").write_text(text, encoding="utf-8")
    return root


def test_without_the_section_the_path_is_legacy(tmp_path: Path) -> None:
    """Норма: конфиг без раздела `composition` собирает колоду старым путём."""
    default = _configs(tmp_path, "seed: 7\n") / "default.yaml"

    assert load_run_config(config_path=default).composition.path == "legacy"


def test_the_shipped_default_is_legacy() -> None:
    """Норма: до приёмки плана Б репозиторий собирает колоду старым путём."""
    assert load_run_config().composition.path == "legacy"


def test_a_profile_overrides_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма: профиль прогона переключает путь, не трогая базу."""
    root = _configs(
        tmp_path,
        "composition:\n  path: legacy\n",
        profiles={"plan_b": "composition:\n  path: by_example\n"},
    )
    monkeypatch.setattr(config, "CONFIGS_DIR", root)

    assert load_run_config(profile="plan_b").composition.path == "by_example"


def test_a_typo_in_the_path_fails_loading() -> None:
    """Нарушитель: опечатка в пути — ошибка загрузки, а не молчаливый `legacy`."""
    with pytest.raises(ValidationError):
        RunConfig.model_validate({"composition": {"path": "by-example"}})


def test_by_example_refuses_before_the_text_is_written_for_the_places() -> None:
    """Нарушитель: без композиции под места путь `by_example` отказывает и называет причину.

    До `the-assign-node` отказ называл недостающий узел `assign`; узел есть, недостаёт change 3.
    """
    with pytest.raises(PipelineError, match="the-text-is-written-for-the-places"):
        ensure_composition_path("by_example")


def test_a_run_on_by_example_does_not_start(tmp_path: Path) -> None:
    """Нарушитель: прогон с `by_example` падает до графа — ни модели, ни файлов."""
    run = RunConfig.model_validate({"composition": {"path": "by_example"}})
    deps = Deps(
        brief=Brief(purpose="report", audience="правление"), run=run, out_dir=tmp_path / "out"
    )

    with pytest.raises(PipelineError, match="the-text-is-written-for-the-places"):
        asyncio.run(
            generate_variant(tmp_path / "t.pptx", [], variant=None, deps=deps, seed=1)  # type: ignore[arg-type]
        )
    assert not deps.out_dir.exists()


def test_legacy_passes_the_start() -> None:
    """Норма: старый путь проверку старта проходит."""
    ensure_composition_path("legacy")


@pytest.mark.parametrize(
    ("state", "expected"),
    [({"composition_path": "legacy"}, "legacy"), ({}, "legacy")],
    ids=["named", "old-checkpoint"],
)
def test_the_report_names_the_path(
    tmp_path: Path, state: dict[str, str], expected: str
) -> None:
    """Норма: `run.json` называет путь; чекпойнт до 30.09 собран путём `legacy`."""
    result = RunResult(variant="A", run_id="r1", out_dir=tmp_path, state=state)  # type: ignore[arg-type]

    assert result.report()["composition_path"] == expected
