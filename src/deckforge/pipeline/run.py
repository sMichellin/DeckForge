"""Запуск графа: сборка зависимостей, прогон варианта, отчёт. Change (17).

Транспорт (CLI, API потока C) зовёт отсюда и больше ничего не знает про LangGraph.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deckforge.config import RunConfig, load_yaml
from deckforge.domain.content import Brief
from deckforge.domain.variants import VariantProfile
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.budget import BudgetTracker
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.graph import build_graph
from deckforge.pipeline.state import DeckState
from deckforge.registry import load_variant_profiles

#: Что умеет прочитать ingestion (change 7). Каталог обходится по этому списку,
#: иначе в контент-пакет попадут .DS_Store и временные файлы редактора.
CONTENT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".docx",
        ".pdf",
        ".pptx",
        ".html",
        ".htm",
        ".xlsx",
        ".xlsm",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
    }
)

RUN_REPORT_NAME = "run.json"


def load_brief(path: Path) -> Brief:
    """`brief.yaml` → `Brief`. Бриф — вход пользователя, а не конфиг запуска."""
    return Brief.model_validate(load_yaml(path))


def collect_content_paths(source: Path) -> list[Path]:
    """Файл — сам по себе; каталог — все пригодные файлы внутри, в порядке имени."""
    if source.is_file():
        return [source]
    files = sorted(
        p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in CONTENT_SUFFIXES
    )
    if not files:
        raise ValueError(f"в {source} нет ни одного файла, который умеет читать ingestion")
    return files


@asynccontextmanager
async def open_checkpointer(path: Path | None) -> AsyncIterator[Any]:
    """Чекпойнт sqlite по пути, иначе — память.

    Без чекпойнтера HITL невозможен: прерванный граф нечем возобновить.
    """
    if path is None:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        yield saver


@dataclass(slots=True)
class RunResult:
    """Итог одного варианта: что получилось и чего не получилось."""

    variant: str
    run_id: str
    out_dir: Path
    state: DeckState

    @property
    def exports(self) -> dict[str, Path]:
        return dict(self.state.get("exports") or {})

    @property
    def interrupted(self) -> bool:
        """Граф остановлен на HITL и ждёт выбора человека."""
        return "__interrupt__" in self.state

    def report(self) -> dict[str, Any]:
        """Отчёт прогона. Всё, что не отработало, названо здесь, а не замолчано."""
        audit = self.state.get("audit")
        plan = self.state.get("plan")
        timings = dict(self.state.get("stage_timings_s") or {})
        return {
            "run_id": self.run_id,
            "variant": self.variant,
            "seed": self.state.get("seed"),
            "slides": len(self.state["deck"].slides) if "deck" in self.state else 0,
            "planned_slides": len(plan.slides) if plan is not None else 0,
            "exports": {fmt: str(path) for fmt, path in self.exports.items()},
            "stage_timings_s": timings,
            "total_s": round(sum(timings.values()), 3),
            "audit": audit.summary.model_dump(mode="json") if audit is not None else None,
            "findings": audit.summary.errors + audit.summary.warnings if audit else 0,
            "skipped_checks": list(self.state.get("skipped_checks") or []),
            "degradations": list(self.state.get("degradations") or []),
            "notes": list(self.state.get("notes") or []),
            "errors": list(self.state.get("errors") or []),
        }

    def write_report(self) -> Path:
        path = self.out_dir / RUN_REPORT_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.report(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path


def build_deps(
    brief: Brief,
    run: RunConfig,
    out_dir: Path,
    *,
    cache_dir: Path | None = None,
    asset_dir: Path | None = None,
    interactive: bool = False,
    profile: str | None = None,
) -> Deps:
    """Живые клиенты по реестру моделей (`configs/models.yaml`).

    Роль, которой в реестре нет, — не ошибка запуска: без `llm_fast` не сработает рычаг
    деградации, без `vlm_judge` аудит останется детерминированным. Оба случая видны
    в отчёте, а колода собирается.
    """
    from deckforge.inference.factory import client_for, vlm_judge

    def maybe(role: str) -> Any | None:
        try:
            return client_for(role)
        except (KeyError, ValueError):
            return None

    def maybe_judge(role: str) -> Any | None:
        try:
            return vlm_judge(role)
        except (KeyError, ValueError):
            return None

    return Deps(
        brief=brief,
        run=run,
        out_dir=out_dir,
        llm=maybe(run.models.get("planning", "llm_main")),
        llm_fast=maybe(run.models.get("bulk", "llm_fast")),
        vlm=maybe_judge(run.models.get("judge", "vlm_judge")),
        layout_vlm=maybe_judge(run.models.get("judge", "vlm_judge")),
        fonts=FontLibrary.default(),
        cache_dir=cache_dir,
        asset_dir=asset_dir,
        work_dir=out_dir,
        budget=BudgetTracker(total_budget_s=run.time_budget_s),
        prompt_profile=profile,
        interactive=interactive,
    )


def initial_state(
    template: Path, content_paths: Iterable[Path], variant: VariantProfile, seed: int, run_id: str
) -> DeckState:
    return {
        "run_id": run_id,
        "seed": seed,
        "template_path": template,
        "content_paths": list(content_paths),
        "variant": variant,
        "fix_round": 0,
    }


async def generate_variant(
    template: Path,
    content_paths: Iterable[Path],
    variant: VariantProfile,
    deps: Deps,
    *,
    seed: int,
    checkpoint_path: Path | None = None,
    run_id: str | None = None,
) -> RunResult:
    """Один вариант вёрстки — один прогон графа."""
    identifier = run_id or uuid.uuid4().hex[:12]
    deps.out_dir.mkdir(parents=True, exist_ok=True)

    async with open_checkpointer(checkpoint_path) as saver:
        graph = build_graph(checkpointer=saver)
        final = await graph.ainvoke(
            initial_state(template, content_paths, variant, seed, identifier),
            config={"configurable": {"thread_id": f"{identifier}:{variant.variant_id}"}},
            context=deps,
        )
    return RunResult(
        variant=variant.variant_id, run_id=identifier, out_dir=deps.out_dir, state=final
    )


def variants_for(names: Iterable[str]) -> list[VariantProfile]:
    """Имена вариантов → профили из `configs/variants.yaml` (C7)."""
    profiles = load_variant_profiles()
    wanted = [name.strip().upper() for name in names]
    missing = [name for name in wanted if name not in profiles]
    if missing:
        known = ", ".join(sorted(profiles))
        raise ValueError(f"нет профиля варианта {', '.join(missing)} (есть: {known})")
    return [profiles[name] for name in wanted]
