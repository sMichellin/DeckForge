"""Отчёт прогона называет находки и решение вписывания. RG37 и RG39
(`docs/agents/tasks-25-09.md`).

`run.json` хранил только счёт находок (`"findings": 28`), а чекпойнт их в читаемом
виде не несёт: разбор «какие именно ошибки остались» 25.09 воспроизвести не удалось
ни одним из двух способов, работавших 24.09.

Цена этого выяснилась назавтра. Дефект RG39 — заголовок WorkSpace s05 в две строки
поверх тела — пришлось разбирать опытом на живом шаблоне: вписывание опускало кегль
36 → 23,4 pt, писатель ставил кегль макета, и увидеть расхождение было негде.
Поэтому здесь же проверяется вторая половина: **писатель ставит найденный кегль,
когда кегль автора знает каталог**, даже если у фигуры примера его нет.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deckforge.domain.audit import AuditReport, AuditSummary, Finding
from deckforge.domain.enums import Severity, TextRole
from deckforge.domain.slide import DeckIR, FitResult, SlideIR, TextBlock
from deckforge.pipeline.run import RunResult


def finding(check_id: str, severity: Severity, slide_id: str) -> Finding:
    return Finding(
        finding_id=f"f-{check_id}-{slide_id}",
        check_id=check_id,
        deterministic=True,
        severity=severity,
        slide_id=slide_id,
        block_id="b1",
        message=f"{check_id} на {slide_id}",
    )


def report_of(audit: AuditReport | None, deck: DeckIR | None) -> dict[str, Any]:
    """Отчёт прогона на подготовленном состоянии: ни графа, ни файлов."""
    state: dict[str, Any] = {}
    if audit is not None:
        state["audit"] = audit
    if deck is not None:
        state["deck"] = deck
    result = RunResult(variant="A", run_id="r01", out_dir=Path("."), state=state)  # type: ignore[arg-type]
    return result.report()


def audit_of(*findings: Finding) -> AuditReport:
    errors = sum(1 for f in findings if f.severity is Severity.ERROR)
    warnings = sum(1 for f in findings if f.severity is Severity.WARNING)
    return AuditReport(
        deck_id="d01",
        variant="A",
        summary=AuditSummary(errors=errors, warnings=warnings, infos=0, passed=0),
        findings=list(findings),
    )


# --- RG37: состав находок и решение вписывания ------------------------------------


def test_the_report_names_every_finding_not_just_counts_them() -> None:
    """Нарушитель прежнего отчёта: два числа вместо состава.

    Ошибки идут раньше предупреждений: так отчёт читают, а не по порядку проверок.
    """
    audit = audit_of(
        finding("layout.text_overflow", Severity.WARNING, "s03"),
        finding("integrity.empty_slide", Severity.ERROR, "s07"),
    )

    detail = report_of(audit, None)["findings_detail"]

    assert [item["check_id"] for item in detail] == [
        "integrity.empty_slide",
        "layout.text_overflow",
    ]
    assert detail[0]["severity"] == "error"
    assert detail[0]["slide_id"] == "s07"
    assert detail[0]["block_id"] == "b1"


def test_the_report_carries_what_the_fitting_decided() -> None:
    """Решение вписывания по каждому блоку — то, чего не хватило для разбора RG39."""
    slide = SlideIR(
        slide_id="s05", layout_id="l01", variant="A", recipe_id="ex017",
        blocks=[TextBlock(block_id="b1", role=TextRole.TITLE, text="Заголовок", zone_id="z709")],
        fit_report={
            "b1": FitResult(final_size_pt=23.4, overflow=False, lines=2, strategy="shrink")
        },
    )
    deck = DeckIR(deck_id="d01", template_id="t01", variant="A", seed=1, slides=[slide])

    fit = report_of(None, deck)["fit"]

    assert fit["s05/b1"] == {
        "size_pt": 23.4, "strategy": "shrink", "overflow": False, "lines": 2
    }


def test_a_report_without_an_audit_says_so_without_breaking() -> None:
    """Норма: аудита в состоянии нет — состав пуст, отчёт собирается."""
    assert report_of(None, None)["findings_detail"] == []
    assert report_of(None, None)["fit"] == {}


# --- RG39: почему заголовок не пересчитывается --------------------------------------
#
# Опыт на живом шаблоне (WorkSpace, рецепт ex017) показал: вписывание своё дело делает —
# зона заголовка с учётом соседа снизу даёт 818 517 EMU, и заголовок пересчитывается
# 36 → 23,4 pt, две строки, 713 232 EMU, переполнения нет. В файл этот кегль не уходит:
# у прогона фигуры-примера нет `sz`, и писатель по решению D04 не трогает ничего.
#
# Обойти D04 через `Zone.size_pt` нельзя — этот путь уже пробовали, и тест
# `test_a_run_without_the_authors_size_is_left_alone` держит его результат: VK Tech s03
# падал 16 → 7,8 pt, VK Education s04/s11 рос 36 → 39. Каталог для унаследованного кегля
# даёт не то число.
#
# Чтобы закрыть RG39 честно, нужен признак «кегль задан явно» у фигуры примера
# (`ExampleShape`), которого сегодня нет: `size_pt` не отличает заданный кегль
# от унаследованного. Это RG42, поток C (парсер) плюс поле в домене — тимлид.
