"""Снимок готового прогона: чтение из чекпойнта, фикстура, переаудит без модели.

План Б, change `the-deck-is-audited-offline` (6б). Зачем: до него любую проверку аудита
и любую правку вёрстки можно было перемерить только полным прогоном на стенде —
205–376 с и ключ от стенда. Прогон же уже оставил всё нужное в чекпойнте LangGraph:
план, IR колоды, контент, манифест и дизайн-систему. Снимок достаёт их оттуда один раз
и кладёт фикстурой в репозиторий — и потоки плана Б меряют свою правку за секунды,
без модели и без стенда.

Снимок читается из двух мест:

* каталог прогона стенда (`checkpoint.sqlite` рядом, `out/run.json`) — финальное состояние
  графа по той же нити «прогон:вариант», что и при генерации;
* фикстура (`plan.json.gz`, `deck.json.gz`, …) — то же самое, сжатое, без sqlite.

Превью слайдов в снимок не входят: это картинки на сотни килобайт, а проверки, которым
они нужны, без них пропускаются и называются в `skipped_checks` — «не мерили», а не ноль.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deckforge.designsystem import DesignSystem
from deckforge.domain.audit import AuditReport
from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan
from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest

CHECKPOINT_NAME = "checkpoint.sqlite"
#: Файлы фикстуры: поле снимка → модель. Порядок — порядок записи.
MODELS: dict[str, type[Any]] = {
    "plan": DeckPlan,
    "deck": DeckIR,
    "content": ContentPackage,
    "manifest": TemplateManifest,
    "design_system": DesignSystem,
}
RUN_REPORT = "run.json"


class ReplayError(RuntimeError):
    """Снимок не собрать: нет чекпойнта, нити или нужного поля состояния."""


@dataclass
class RunSnapshot:
    """Всё, что прогон знал о колоде к концу, — без картинок и без модели."""

    run_id: str
    plan: DeckPlan
    deck: DeckIR
    content: ContentPackage
    manifest: TemplateManifest
    design_system: DesignSystem
    #: `run.json` прогона: выбор примеров, заметки, находки — по нему считает мерило.
    report: dict[str, Any] = field(default_factory=dict)
    #: Файл колоды и файл шаблона, если они лежат рядом со снимком. В фикстуру не едут:
    #: шаблоны кейса весят 13–33 МБ.
    pptx_path: Path | None = None
    template_path: Path | None = None


def _run_id_of(run_dir: Path) -> str:
    """Идентификатор прогона: из `run.json`, иначе — имя каталога, как кладёт стенд."""
    report = _report_of(run_dir)
    return str(report.get("run_id") or run_dir.name)


def _report_of(run_dir: Path) -> dict[str, Any]:
    for candidate in (run_dir / "out" / RUN_REPORT, run_dir / RUN_REPORT):
        if candidate.is_file():
            data: dict[str, Any] = json.loads(candidate.read_text(encoding="utf-8"))
            return data
    return {}


def _local(path: Path | None) -> Path | None:
    return path if path is not None and path.is_file() else None


async def _checkpoint_state(run_dir: Path, run_id: str, variant: str) -> dict[str, Any]:
    from deckforge.pipeline.graph import build_graph
    from deckforge.pipeline.run import open_checkpointer, thread_id

    async with open_checkpointer(run_dir / CHECKPOINT_NAME) as saver:
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": thread_id(run_id, variant)}}
        snapshot = await graph.aget_state(config)
    values: dict[str, Any] = dict(snapshot.values or {})
    if not values:
        raise ReplayError(f"{run_dir}: в чекпойнте нет нити {thread_id(run_id, variant)}")
    return values


def from_checkpoint(run_dir: Path, *, variant: str = "A") -> RunSnapshot:
    """Снимок каталога прогона стенда: финальное состояние графа из `checkpoint.sqlite`."""
    if not (run_dir / CHECKPOINT_NAME).is_file():
        raise ReplayError(f"{run_dir}: нет {CHECKPOINT_NAME}")
    run_id = _run_id_of(run_dir)
    state = asyncio.run(_checkpoint_state(run_dir, run_id, variant))
    missing = [name for name in MODELS if state.get(name) is None]
    if missing:
        raise ReplayError(f"{run_dir}: прогон не дошёл до конца — в состоянии нет {missing}")
    return RunSnapshot(
        run_id=run_id,
        report=_report_of(run_dir),
        pptx_path=_local(run_dir / "out" / "deck.pptx"),
        template_path=_local(run_dir / "in" / "template.pptx"),
        **{name: state[name] for name in MODELS},
    )


def save_fixture(snapshot: RunSnapshot, out_dir: Path) -> list[Path]:
    """Снимок фикстурой: модели — сжатым JSON, `run.json` — как есть (его читают глазами)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in MODELS:
        path = out_dir / f"{name}.json.gz"
        payload = getattr(snapshot, name).model_dump_json().encode("utf-8")
        # `mtime=0`: одинаковый снимок — одинаковые байты, и фикстура не меняется в git
        # от перевыгрузки.
        path.write_bytes(gzip.compress(payload, mtime=0))
        written.append(path)
    report = out_dir / RUN_REPORT
    report.write_text(
        json.dumps(snapshot.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written.append(report)
    return written


def from_fixture(fixture_dir: Path) -> RunSnapshot:
    """Снимок из фикстуры, выгруженной `save_fixture`."""
    loaded: dict[str, Any] = {}
    for name, model in MODELS.items():
        path = fixture_dir / f"{name}.json.gz"
        if not path.is_file():
            raise ReplayError(f"{fixture_dir}: нет {path.name}")
        loaded[name] = model.model_validate_json(gzip.decompress(path.read_bytes()))
    report = _report_of(fixture_dir)
    run_id = str(report.get("run_id") or fixture_dir.name)
    return RunSnapshot(run_id=run_id, report=report, **loaded)


def load_snapshot(path: Path, *, variant: str = "A") -> RunSnapshot:
    """Снимок из каталога прогона или из фикстуры — что лежит, то и читается."""
    if (path / CHECKPOINT_NAME).is_file():
        return from_checkpoint(path, variant=variant)
    return from_fixture(path)


@dataclass
class Reaudit:
    """Итог переаудита: отчёт и проверки, которые без превью или файла колоды не шли."""

    report: AuditReport
    skipped_checks: list[str]


async def reaudit(
    snapshot: RunSnapshot, *, run_params: dict[str, Any] | None = None
) -> Reaudit:
    """Детерминированный аудит снимка — без судьи и без превью.

    Судья-VLM не зовётся: переаудит нужен, чтобы мерить правку за секунды, а судья стоит
    68 с на слайд за голос. Проверки, которым нужны превью или файл колоды, без них
    пропускаются и называются в `skipped_checks` — «не мерили», а не «ноль находок».
    """
    from deckforge.audit.runner import AuditRunner

    runner = AuditRunner(run_params=run_params or {})
    report = await runner.run(
        snapshot.deck,
        snapshot.manifest,
        snapshot.content,
        deck_path=snapshot.pptx_path,
        vlm=None,
        design_system=snapshot.design_system,
    )
    return Reaudit(report=report, skipped_checks=list(runner.skipped_checks))
