"""Запуск графа: сборка зависимостей, прогон варианта, отчёт. Change (17).

Транспорт (CLI, API потока C) зовёт отсюда и больше ничего не знает про LangGraph.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deckforge.config import RunConfig, load_yaml
from deckforge.designsystem import DesignSystem
from deckforge.designsystem.usage import usage as design_system_usage
from deckforge.domain.content import Brief
from deckforge.domain.enums import Severity
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


def _prompt_versions(state: Mapping[str, Any]) -> list[str]:
    """Версии промптов, которыми собрана колода, — из провенанса слайдов.

    Отчёт называет то, что звали, а не то, что объявлено активным: расхождение между
    этими двумя вещами уже один раз прошло незамеченным (прогоны RG20, `slide_composer@1.0.0`
    при активной `1.4.0`).
    """
    deck = state.get("deck")
    if deck is None:
        return []
    return sorted({
        slide.provenance.prompt_version
        for slide in deck.slides
        if slide.provenance.prompt_version
    })


def design_system_summary(ds: DesignSystem | None) -> dict[str, Any] | None:
    """Числа разделов дизайн-системы для `run.json` (DG2).

    По ним видно, что конвейер разобрал шаблон, а не взял заготовку: у разных шаблонов
    числа разные, а у шаблона без слайдов-примеров измеряемые разделы пусты. Самих
    значений здесь нет — они в чекпойнте, а сводка прогона остаётся сводкой.
    """
    if ds is None:
        return None
    return {
        "template_id": ds.template_id,
        "type_levels": len(ds.typography.steps),
        "theme_slots": len(ds.theme.slots),
        "spacing_steps": len(ds.grid.spacing.steps_emu),
        "color_roles": len(ds.palette_roles),
        "combinations": len(ds.combinations),
        "contrast_pairs": len(ds.contrast_pairs),
        "contrast_defects": len(ds.contrast_defects),
        "fonts_in_use": len(ds.fonts_in_use),
        "components": len(ds.components),
        "synthesized": len(ds.synthesized),
        "assembly_rules": len(ds.assembly_rules),
    }


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

    def pending_findings(self) -> list[dict[str, Any]]:
        """Находки, на которые граф ждёт ответа. Пусто, если он не прерван.

        Разбор `__interrupt__` живёт здесь, а не в транспорте: его форма принадлежит
        LangGraph, а API и CLI про LangGraph знать не должны (ARCHITECTURE.md §3).
        """
        # Ключ не объявлен в `DeckState`: его кладёт LangGraph, а не наши узлы.
        payloads: Any = self.state.get("__interrupt__") or []
        findings: list[dict[str, Any]] = []
        for item in payloads:
            value = getattr(item, "value", item)
            if isinstance(value, dict):
                findings.extend(value.get("findings") or [])
        return findings

    def report(self) -> dict[str, Any]:
        """Отчёт прогона. Всё, что не отработало, названо здесь, а не замолчано."""
        audit = self.state.get("audit")
        plan = self.state.get("plan")
        timings = dict(self.state.get("stage_timings_s") or {})
        design = self.state.get("design_system")
        notes = list(self.state.get("notes") or [])
        # Что из ДС стоит на колоде (`design-system-usage-in-the-run`). Без этого по отчёту
        # видно, что ДС собрана, но не видно, собрана ли по ней колода.
        usage = design_system_usage(self.state["deck"], design) if "deck" in self.state else None
        if usage is not None and usage["slides_total"] and not usage["slides_with_elements"]:
            notes.append(
                "дизайн-система: ни на одном слайде нет её элементов — колода собрана "
                "только плейсхолдерами макетов"
            )
        if usage is not None and usage["slides_total"] and not usage["slides_by_recipe"]:
            notes.append(
                "рецептов нет — слайды собраны из макетов"
            )
        # Слайд с одним заголовком — пустое чёрное поле на девять десятых экрана. Его
        # не ловит ни `check_deck_readable` (нечего мерить), ни глаз, пока колоду
        # не открыли. Поэтому число едет первым в заметках, а не только в `usage` (RG28).
        if usage is not None and (lonely := usage["slides_title_only"]):
            notes.append(
                f"слайдов только с заголовком: {lonely} из {usage['slides_total']} — "
                "тело слайда до файла не доехало"
            )
        return {
            "run_id": self.run_id,
            "variant": self.variant,
            # Какими версиями промптов собрана колода. Берётся из провенанса слайдов,
            # то есть из того, что действительно звали, а не из реестра. Прогоны RG20
            # (24.09) шли на `slide_composer@1.0.0` при активной `1.4.0` — профиль
            # закреплял версию молча, и по отчёту это было не видно.
            "prompt_versions": _prompt_versions(self.state),
            "seed": self.state.get("seed"),
            "slides": len(self.state["deck"].slides) if "deck" in self.state else 0,
            "planned_slides": len(plan.slides) if plan is not None else 0,
            # Число слайдов на выбор (Т1): задано человеком или подобрано, и почему.
            "slides_decision": self.state.get("slides_decision"),
            # Почему каждый слайд собран так (Т7): рецепт или макет, путь выбора.
            "slide_choices": list(self.state.get("slide_choices") or []),
            "exports": {fmt: str(path) for fmt, path in self.exports.items()},
            # Дизайн-система файлами рядом с колодой (Т2): по ним проверяют, по какой
            # системе собрана колода, не запуская отдельную команду.
            "design_system_files": {
                kind: str(path)
                for kind, path in (self.state.get("design_system_files") or {}).items()
            },
            "stage_timings_s": timings,
            "total_s": round(sum(timings.values()), 3),
            "audit": audit.summary.model_dump(mode="json") if audit is not None else None,
            "findings": audit.summary.errors + audit.summary.warnings if audit else 0,
            # Состав находок, а не только счёт (RG37). До этого в отчёте стояло число,
            # и разобрать «какие именно ошибки остались» было нечем: чекпойнт их
            # в читаемом виде не несёт. Владельцу на сдаче нужен состав, а не число,
            # а починке — слайд и блок, на которые находка указывает.
            "findings_detail": self._findings_detail(audit),
            # Что вписывание решило по каждому блоку (RG37). Без этого дефект RG39
            # пришлось разбирать опытом: заголовок был пересчитан на 23,4 pt, а в файл
            # уехал кеглем макета, и увидеть расхождение было негде.
            "fit": self._fit_detail(self.state.get("deck")),
            # Метрики оформления по каждому слайду (C7): находка есть только
            # у нарушителя, а сравнивать колоды надо по величинам, которые есть у всех.
            "design_metrics": dict(self.state.get("design_metrics") or {}),
            # Дизайн-система шаблона (DG2): числа разделов, а не сами значения.
            # `None` — узел `parse` до неё не дошёл, и это видно, а не замолчано.
            "design_system": design_system_summary(design),
            "design_system_usage": usage,
            "skipped_checks": list(self.state.get("skipped_checks") or []),
            "degradations": list(self.state.get("degradations") or []),
            "notes": notes,
            "errors": list(self.state.get("errors") or []),
        }

    @staticmethod
    def _findings_detail(audit: Any) -> list[dict[str, Any]]:
        """Находки списком: важность, проверка, слайд, блок и текст.

        Порядок — ошибки раньше предупреждений, внутри — по слайду: так читают отчёт,
        а не по порядку проверок.
        """
        order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        found = list(getattr(audit, "findings", None) or [])
        found.sort(key=lambda f: (order.get(f.severity, 9), f.slide_id or "", f.check_id))
        return [
            {
                "severity": finding.severity.value,
                "check_id": finding.check_id,
                "slide_id": finding.slide_id,
                "block_id": finding.block_id,
                "message": finding.message,
                "auto_fix_applied": finding.auto_fix_applied,
            }
            for finding in found
        ]

    @staticmethod
    def _fit_detail(deck: Any) -> dict[str, dict[str, Any]]:
        """Решение вписывания по каждому блоку: кегль, стратегия, переполнение, строки.

        Ключ — `слайд/блок`. Пустой `fit_report` у слайда — не ошибка: блок без рамки
        вписывать не по чему, и такой слайд в ответе просто не появится.
        """
        detail: dict[str, dict[str, Any]] = {}
        for slide in getattr(deck, "slides", None) or []:
            for block_id, fit in (slide.fit_report or {}).items():
                detail[f"{slide.slide_id}/{block_id}"] = {
                    "size_pt": fit.final_size_pt,
                    "strategy": fit.strategy,
                    "overflow": fit.overflow,
                    "lines": fit.lines,
                }
        return detail

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


def thread_id(run_id: str, variant: VariantProfile | str) -> str:
    """Ключ чекпойнта. Возобновление обязано попасть в ту же нить, что и прогон."""
    name = variant if isinstance(variant, str) else variant.variant_id
    return f"{run_id}:{name}"


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
            config={"configurable": {"thread_id": thread_id(identifier, variant)}},
            context=deps,
        )
    return RunResult(
        variant=variant.variant_id, run_id=identifier, out_dir=deps.out_dir, state=final
    )


async def resume_variant(
    variant: VariantProfile,
    deps: Deps,
    *,
    run_id: str,
    selected: Iterable[str],
    checkpoint_path: Path,
) -> RunResult:
    """Продолжение прерванного прогона после выбора человека (HITL).

    Путь до чекпойнта обязателен, и это не придирка: `InMemorySaver` живёт в процессе,
    а смысл HITL ровно в том, что выбор приходит позже и, возможно, в другой воркер.
    Возобновлять из памяти было бы нечего.

    Выбор передаётся списком `finding_id` — тем же, что уехал в `pending_findings()`.
    Узел `hitl` отберёт по нему находки сам: транспорт решает, что чинить, а не как.
    """
    from langgraph.types import Command

    async with open_checkpointer(checkpoint_path) as saver:
        graph = build_graph(checkpointer=saver)
        final = await graph.ainvoke(
            Command(resume=[str(item) for item in selected]),
            config={"configurable": {"thread_id": thread_id(run_id, variant)}},
            context=deps,
        )
    return RunResult(
        variant=variant.variant_id, run_id=run_id, out_dir=deps.out_dir, state=final
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
