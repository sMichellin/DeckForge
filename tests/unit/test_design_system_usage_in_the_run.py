"""Что из дизайн-системы стоит на колоде — в отчёте прогона. Change
`design-system-usage-in-the-run`.

Что проверяется:

* какой блок считается элементом ДС: показатель, схема, цитата, callout, нумерованный
  и иконочный список — да; абзац и маркированный список — нет, их оформляет макет;
* сводка по колоде: элементы по слайдам, доля слайдов с элементом, что ДС умеет,
  а колода не взяла;
* отчёт прогона: раздел `design_system_usage` есть, а колода без единого элемента ДС
  названа в заметках (нарушитель) и не названа, когда элементы есть (норма);
* `scripts/run_metrics.py` выводит долю слайдов с элементом ДС;
* сквозной прогон графа на подделке модели пишет раздел в `run.json`.

Шаблоны — синтетический манифест `conftest` и стандартный шаблон python-pptx (C6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from deckforge.designsystem import DesignSystem, derive
from deckforge.designsystem.usage import available, element_of, slide_elements, usage
from deckforge.domain.enums import CalloutTone, ListStyle, SmartArtPattern
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    CalloutBlock,
    DeckIR,
    QuoteBlock,
    SmartArtBlock,
)
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.run import RUN_REPORT_NAME, RunResult
from tests.integration.test_native_objects import build_template
from tests.integration.test_pipeline_end_to_end import run_pipeline
from tests.unit._audit_builders import body, deck, kpi, slide, title

ITEMS = [BulletItem(text="Разбор шаблона"), BulletItem(text="Сборка колоды")]


def listing(style: ListStyle | None, block_id: str = "l") -> BulletsBlock:
    items = ITEMS
    if style is ListStyle.ICON:
        items = [item.model_copy(update={"icon": "search"}) for item in ITEMS]
    return BulletsBlock(block_id=block_id, items=items, style=style)


def callout(tone: CalloutTone, block_id: str = "c") -> CalloutBlock:
    return CalloutBlock(block_id=block_id, tone=tone, text="Вывод слайда")


@pytest.fixture
def design(manifest: TemplateManifest) -> DesignSystem:
    return derive(manifest)


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    """Шаблон, материалы и бриф сквозного прогона — те же, что в `test_pipeline_end_to_end`.

    Своя фикстура, а не импорт чужой: импортированная фикстура в параметре теста —
    это переопределение имени, и ruff CI на нём падает (F811).
    """
    content = tmp_path / "content"
    content.mkdir()
    (content / "факты.md").write_text(
        "# Итоги года\n\nВыручка выросла на 37,5 % за год.\n\nКлиентов стало более 500.\n",
        encoding="utf-8",
    )
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        "purpose: product\naudience: правление\ntarget_slides: 6\nlanguage: ru\n",
        encoding="utf-8",
    )
    return {
        "template": build_template(tmp_path / "template.pptx"),
        "content": content,
        "brief": brief,
        "root": tmp_path,
    }


def mixed_deck() -> DeckIR:
    """Три слайда: абзац, показатель с callout «инсайт», нумерованный список."""
    return deck(
        slide(title(), body(), slide_id="s01"),
        slide(title(), kpi(), callout(CalloutTone.INSIGHT), slide_id="s02"),
        slide(title(), listing(ListStyle.NUMBERED), slide_id="s03"),
    )


# --- что считается элементом ДС -----------------------------------------------------


@pytest.mark.parametrize(
    ("block", "name"),
    [
        (kpi(), "kpi"),
        (SmartArtBlock(block_id="s", pattern=SmartArtPattern.MATRIX, items=["А", "Б"]), "smartart"),
        (QuoteBlock(block_id="q", text="Слова", author="Автор"), "quote"),
        (callout(CalloutTone.INSIGHT), "callout:insight"),
        (callout(CalloutTone.RISK), "callout:risk"),
        (listing(ListStyle.NUMBERED), "bullets:numbered"),
        (listing(ListStyle.ICON), "bullets:icon"),
    ],
)
def test_a_block_drawn_by_the_design_system_is_an_element(block: object, name: str) -> None:
    assert element_of(block) == name  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "block",
    [title(), body(), listing(None), listing(ListStyle.BULLETED)],
    ids=["заголовок", "абзац", "список без стиля", "маркированный список"],
)
def test_a_block_the_layout_draws_is_not_an_element(block: object) -> None:
    """Их оформляет плейсхолдер макета: считать их за ДС значит завысить долю."""
    assert element_of(block) is None  # type: ignore[arg-type]


def test_an_element_is_named_once_per_slide() -> None:
    two = slide(title(), callout(CalloutTone.RISK, "c1"), callout(CalloutTone.RISK, "c2"))
    assert slide_elements(two) == ["callout:risk"]


# --- сводка по колоде -----------------------------------------------------------------


def test_the_summary_names_elements_by_slide_and_the_share(design: DesignSystem) -> None:
    summary = usage(mixed_deck(), design)

    assert summary["slides"] == {
        "s01": [],
        "s02": ["kpi", "callout:insight"],
        "s03": ["bullets:numbered"],
    }
    assert summary["slides_total"] == 3
    assert summary["slides_with_elements"] == 2
    assert summary["share"] == pytest.approx(0.667)
    assert summary["elements"] == {"bullets:numbered": 1, "callout:insight": 1, "kpi": 1}


def test_what_the_design_system_can_draw_but_the_deck_did_not_take(
    design: DesignSystem,
) -> None:
    unused = usage(mixed_deck(), design)["unused"]
    assert unused == ["smartart", "quote", "callout:risk", "bullets:icon"]


def test_an_element_the_template_lacks_is_not_counted_as_unused(design: DesignSystem) -> None:
    """Шаблон без цитаты: «колода не взяла цитату» — не вопрос к плану."""
    poor = design.model_copy(
        update={"synthesized": [item for item in design.synthesized if item.kind != "quote"]}
    )
    assert "quote" not in available(poor)
    assert {"kpi", "smartart"} <= set(available(poor))
    assert "quote" not in usage(mixed_deck(), poor)["unused"]


def test_without_a_design_system_nothing_is_unused() -> None:
    assert usage(mixed_deck(), None)["unused"] == []


# --- отчёт прогона ----------------------------------------------------------------------


def report_for(tmp_path: Path, the_deck: DeckIR, design: DesignSystem) -> dict[str, object]:
    result = RunResult(
        variant="A",
        run_id="r1",
        out_dir=tmp_path,
        state={"deck": the_deck, "design_system": design, "notes": ["план: прежняя заметка"]},
    )
    return result.report()


def test_a_deck_without_design_system_elements_is_named(
    tmp_path: Path, design: DesignSystem
) -> None:
    plain = deck(slide(title(), body(), slide_id="s01"), slide(title(), slide_id="s02"))
    report = report_for(tmp_path, plain, design)

    assert report["design_system_usage"]["share"] == 0.0  # type: ignore[index]
    notes = report["notes"]
    assert "план: прежняя заметка" in notes  # type: ignore[operator]
    assert any("ни на одном слайде нет её элементов" in note for note in notes)  # type: ignore[union-attr]


def test_a_deck_with_design_system_elements_is_not_named(
    tmp_path: Path, design: DesignSystem
) -> None:
    report = report_for(tmp_path, mixed_deck(), design)

    assert report["design_system_usage"]["slides_with_elements"] == 2  # type: ignore[index]
    assert not any("ни на одном слайде" in note for note in report["notes"])  # type: ignore[union-attr]


def test_a_run_stopped_before_the_deck_has_no_usage(tmp_path: Path) -> None:
    result = RunResult(variant="A", run_id="r1", out_dir=tmp_path, state={})
    assert result.report()["design_system_usage"] is None


# --- мерило прогонов -------------------------------------------------------------------


def test_run_metrics_shows_the_share_of_slides_with_an_element(
    tmp_path: Path, design: DesignSystem
) -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import run_metrics
    finally:
        sys.path.remove(str(scripts))

    run_dir = tmp_path / "run1"
    (run_dir / "out").mkdir(parents=True)
    (run_dir / "out" / "run.json").write_text(
        json.dumps(report_for(tmp_path, mixed_deck(), design), ensure_ascii=False),
        encoding="utf-8",
    )
    assert run_metrics.metrics(run_dir)["слайдов с элементом ДС, %"] == pytest.approx(66.7)


# --- сквозной прогон -------------------------------------------------------------------


async def test_the_run_report_carries_the_usage(
    workspace: dict[str, Path],
) -> None:
    """Подделка модели кладёт на слайд один абзац — колода без элементов ДС, и отчёт
    говорит это прямо, а не показывает одни числа разделов ДС."""
    result, _ = await run_pipeline(workspace)
    path = result.write_report()
    assert path.name == RUN_REPORT_NAME
    report = json.loads(path.read_text(encoding="utf-8"))

    usage_part = report["design_system_usage"]
    assert set(usage_part["slides"]) == {s.slide_id for s in result.state["deck"].slides}
    assert usage_part["slides_with_elements"] == 0
    assert "bullets:numbered" in usage_part["unused"]
    assert any("ни на одном слайде нет её элементов" in note for note in report["notes"])
