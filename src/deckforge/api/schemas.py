"""DTO транспорта. Не путать с доменными моделями: API может отдавать урезанный вид."""

from __future__ import annotations

from pydantic import BaseModel


class RunRequest(BaseModel):
    variants: list[str] = ["A", "B", "C"]
    target_slides: int = 12
    language: str = "ru"
    seed: int = 1337


class RunStatus(BaseModel):
    run_id: str
    stage: str
    progress: float
    elapsed_s: float
    error: str | None = None
