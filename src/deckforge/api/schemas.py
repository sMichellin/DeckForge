"""DTO транспорта. Не путать с доменными моделями: API может отдавать урезанный вид.

Доменные модели сюда не протекают сознательно. `Finding` содержит `evidence` с внутренними
ключами, `SlideIR` — координаты в EMU и provenance: интерфейсу это не нужно, а менять
контракт домена из-за формы кнопки нельзя (ARCHITECTURE.md §3).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """Чем запрошен прогон.

    **Один прогон — один вариант вёрстки.** Три варианта это три прогона, и так честнее:
    у каждого свой чекпойнт, своя остановка на выборе фиксов и свой отчёт. Пакетная
    выдача девяти колод (A3) — работа CLI, у которой нет человека в середине.
    """

    variant: str = Field(default="A", pattern=r"^[A-Z]$")
    purpose: str = "report"
    audience: str = "правление"
    #: Сколько слайдов; `null` — подобрать по материалу (Т1).
    target_slides: int | None = Field(default=12, ge=1, le=60)
    language: str = "ru"
    seed: int = 1337
    #: Останавливаться ли на выборе фиксов. Выключено — граф чинит по конфигу и не ждёт.
    interactive: bool = True
    #: Профиль прогона: `configs/profiles/<profile>.yaml` поверх `default.yaml`.
    #: `None` — только база, как было до change (24). Имя проверяет маршрут: здесь
    #: нельзя, DTO не ходит на диск.
    #:
    #: Не путать с `variant`: тот выбирает вариант вёрстки (A/B/C), этот — набор
    #: настроек прогона (аудит, форматы, модели). Слова «профиль» в коде два.
    profile: str | None = None


class FindingView(BaseModel):
    """Находка так, как её показывает интерфейс: подсветить и объяснить.

    `bbox_emu` отдаётся как есть — в EMU, единицах OOXML. Переводить в пиксели здесь
    нельзя: масштаб зависит от того, в каком размере интерфейс показывает превью,
    и знает его только он. Поэтому рядом едет `bbox_rel` — та же рамка в долях слайда:
    ею подсветка рисуется при любом масштабе, а размер слайда знает манифест, который
    до интерфейса не доезжает.
    """

    finding_id: str
    check_id: str
    severity: str
    title: str
    message: str
    slide_id: str | None = None
    block_id: str | None = None
    bbox_emu: dict[str, int] | None = None
    bbox_rel: dict[str, float] | None = None
    auto_fix: str = "none"
    auto_fix_applied: bool = False

    @classmethod
    def of(cls, raw: dict[str, Any]) -> FindingView:
        box = raw.get("bbox_emu") or None
        rel = raw.get("bbox_rel") or None
        return cls(
            finding_id=str(raw.get("finding_id", "")),
            check_id=str(raw.get("check_id", "")),
            severity=str(raw.get("severity", "warning")),
            title=str(raw.get("check_id", "")),
            message=str(raw.get("message", "")),
            slide_id=raw.get("slide_id"),
            block_id=raw.get("block_id"),
            bbox_emu={k: int(box[k]) for k in ("x", "y", "cx", "cy")} if box else None,
            bbox_rel={k: float(rel[k]) for k in ("x", "y", "cx", "cy")} if rel else None,
            auto_fix=str(raw.get("auto_fix", "none")),
            auto_fix_applied=bool(raw.get("auto_fix_applied", False)),
        )


class RunStatus(BaseModel):
    """Где прогон сейчас.

    `state` и `stage` — разные вещи: `stage` это узел графа, `state` — что делать
    интерфейсу. `waiting_choice` означает, что граф остановлен и ждёт человека;
    полоска прогресса в этот момент не двигается не потому, что всё зависло.

    `error` и `degradations` тоже разные вещи. Деградация — это «собрано более дешёвым
    путём», и у прогона `done` она законна; ошибка — «что-то не отработало». У удачного
    прогона `error` пуст, иначе интерфейс красит успех в красное.
    """

    run_id: str
    state: str
    stage: str | None = None
    progress: float = 0.0
    elapsed_s: float = 0.0
    error: str | None = None
    degradations: list[str] = Field(default_factory=list)
    findings: list[FindingView] = Field(default_factory=list)

    @classmethod
    def of(cls, raw: dict[str, Any]) -> RunStatus:
        return cls(
            run_id=str(raw.get("run_id", "")),
            state=str(raw.get("state", "queued")),
            stage=raw.get("stage"),
            progress=float(raw.get("progress", 0.0)),
            elapsed_s=float(raw.get("elapsed_s", 0.0)),
            error=raw.get("error"),
            degradations=[str(item) for item in raw.get("degradations") or []],
            findings=[FindingView.of(item) for item in raw.get("findings") or []],
        )


class FixSelection(BaseModel):
    """Что человек выбрал чинить. Пустой список — законный ответ «ничего не чинить»."""

    finding_ids: list[str] = Field(default_factory=list)


class RunCreated(BaseModel):
    run_id: str
    state: str = "queued"
