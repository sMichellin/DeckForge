"""Скрипты замера. Запрос из #26 и долг change (17).

Скрипт без теста гниёт молча: `bench_time_budget.py` пролежал заглушкой весь change (17)
и никто этого не заметил. Здесь проверяется не красота чисел, а то, что замер что-то
меряет и называет то, чего не померил.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bench_audit_calibration as audit_bench  # noqa: E402
import bench_time_budget as time_bench  # noqa: E402
from deckforge.domain.slide import BulletsBlock, TextBlock  # noqa: E402
from deckforge.domain.template import TemplateManifest  # noqa: E402
from deckforge.layout.fonts import FontLibrary  # noqa: E402
from deckforge.pipeline.run import RunResult  # noqa: E402

# --- замер аудита -------------------------------------------------------------


def test_bench_deck_is_built_from_template_layouts(manifest: TemplateManifest) -> None:
    deck, skipped = audit_bench.build_deck(manifest, None)
    used = {slide.layout_id for slide in deck.slides}
    assert used <= {layout.layout_id for layout in manifest.layouts}
    assert deck.slides, f"колода пуста, пропущено: {skipped}"


def test_every_slide_gets_its_own_text(manifest: TemplateManifest) -> None:
    """Одинаковый текст на всех слайдах дал бы находку про дубли — и замер мерил бы себя."""
    deck, _ = audit_bench.build_deck(manifest, None)
    headlines = [
        block.text
        for slide in deck.slides
        for block in slide.blocks
        if isinstance(block, TextBlock)
    ]
    assert len(set(headlines)) == len(headlines)


def test_bench_text_has_no_numbers(manifest: TemplateManifest) -> None:
    """Иначе `content.numbers_grounded` справедливо ругался бы на выдуманные числа."""
    deck, _ = audit_bench.build_deck(manifest, None)
    texts = [
        block.text if isinstance(block, TextBlock) else " ".join(i.text for i in block.items)
        for slide in deck.slides
        for block in slide.blocks
        if isinstance(block, TextBlock | BulletsBlock)
    ]
    assert not any(ch.isdigit() for text in texts for ch in text)


def test_non_text_placeholders_are_not_filled_with_text(manifest: TemplateManifest) -> None:
    layout = manifest.layouts[1]
    title_idx, body_idx = audit_bench.text_placeholders(layout)
    non_text = {p.idx for p in layout.placeholders if p.ph_type in audit_bench.NON_TEXT}
    assert title_idx not in non_text and body_idx not in non_text


def test_measurement_counts_per_slide() -> None:
    m = audit_bench.Measurement(template="t", slides=4, findings=6, errors=2)
    assert m.per_slide == pytest.approx(1.5)
    assert m.errors_per_slide == pytest.approx(0.5)


def test_empty_deck_does_not_divide_by_zero() -> None:
    m = audit_bench.Measurement(template="t", slides=0, findings=0, errors=0)
    assert m.per_slide == 0.0 and m.errors_per_slide == 0.0


def test_bench_measures_something_on_a_real_package(tmp_path: Path) -> None:
    """Главное свойство замера: он обязан выполнить проверки, а не показать чистый ноль.

    Ровно здесь скрипт и поймал, что прогон аудита не наполнял реестр.
    """
    from tests.integration.test_native_objects import build_template

    template = build_template(tmp_path / "t.pptx")
    measurement = audit_bench.measure(template, FontLibrary.default(), tmp_path / "cache")

    assert measurement.slides > 0
    # Либо находки, либо явно названные пропуски — «тихий ноль» означает, что не мерили.
    assert measurement.findings > 0 or measurement.skipped_checks


def test_skipped_checks_are_named(tmp_path: Path) -> None:
    """Без VLM смысловые проверки не запускаются, и замер обязан это сказать."""
    from tests.integration.test_native_objects import build_template

    template = build_template(tmp_path / "t.pptx")
    measurement = audit_bench.measure(template, None, tmp_path / "cache")
    assert any(check.startswith("content.") for check in measurement.skipped_checks)


# --- замер бюджета ------------------------------------------------------------


def test_percentile_of_one_run_is_that_run() -> None:
    assert time_bench.percentile([42.0], 0.95) == 42.0


def test_percentile_takes_the_worst_of_three() -> None:
    """На трёх прогонах p95 — это худший: интерполяция дала бы число, которого не было."""
    assert time_bench.percentile([10.0, 20.0, 30.0], 0.95) == 30.0
    assert time_bench.percentile([10.0, 20.0, 30.0], 0.5) == 20.0


def test_percentile_of_nothing_is_zero() -> None:
    assert time_bench.percentile([], 0.95) == 0.0


def fake_result(timings: dict[str, float]) -> RunResult:
    return RunResult(
        variant="A",
        run_id="r1",
        out_dir=Path("."),
        state={"stage_timings_s": timings, "seed": 1},  # type: ignore[typeddict-item]
    )


def test_stage_timings_are_collected_across_runs() -> None:
    per_stage = time_bench.table([fake_result({"plan": 1.0}), fake_result({"plan": 3.0})])
    assert per_stage["plan"] == [1.0, 3.0]


def test_report_says_no_when_the_budget_is_blown(capsys: pytest.CaptureFixture[str]) -> None:
    ok = time_bench.report([fake_result({"plan": 400.0})], budget_s=300)
    assert ok is False
    assert "p95" in capsys.readouterr().out


def test_report_says_yes_within_budget(capsys: pytest.CaptureFixture[str]) -> None:
    ok = time_bench.report([fake_result({"plan": 10.0, "compose": 20.0})], budget_s=300)
    assert ok is True
    capsys.readouterr()


# --- сводка по прогонам -------------------------------------------------------


def write_run(root: Path, run_id: str, **report: object) -> Path:
    run = root / run_id
    (run / "out").mkdir(parents=True)
    (run / "out" / "run.json").write_text(
        json.dumps({"slides": 10, "total_s": 150.0, "audit": {"errors": 1, "warnings": 2},
                    "notes": [], **report}, ensure_ascii=False),
        encoding="utf-8",
    )
    return run


def test_run_metrics_counts_what_the_notes_say(tmp_path: Path) -> None:
    """Подрезанный заголовок и потерянный факт видны в заметках прогона — их и считаем."""
    import run_metrics

    run = write_run(
        tmp_path, "aaaa", notes=[
            "слайд s01: заголовок подрезан под рамку макета: 40 → 25 знаков",
            "слайд s02: заголовок подрезан под рамку макета: 38 → 24 знаков",
            "слайд s03: факты f003 на слайд не попали: ни одного их значащего слова в тексте",
        ],
    )
    values = run_metrics.metrics(run)

    assert values["заголовков подрезано"] == 2
    assert values["фактов потеряно"] == 1
    assert values["секунд"] == 150.0


def test_run_metrics_prints_median_and_spread(tmp_path: Path, capsys: pytest.CaptureFixture[str]
                                              ) -> None:
    """Смысл скрипта — показать разброс: по одному прогону судить нельзя."""
    import run_metrics

    trimmed = "слайд s01: заголовок подрезан под рамку макета: 40 → 25 знаков"
    first = write_run(tmp_path, "aaaa", notes=[trimmed], total_s=100.0)
    second = write_run(tmp_path, "bbbb", notes=[trimmed] * 5, total_s=200.0)

    assert run_metrics.main([str(first), str(second)]) == 0
    printed = capsys.readouterr().out

    assert "медиана" in printed and "разброс" in printed
    assert "1–5" in printed, "разброс по заголовкам не показан"
    assert "меньше трёх" in printed, "молчит о том, что двух прогонов мало"


def test_run_metrics_without_runs_explains_itself(capsys: pytest.CaptureFixture[str]) -> None:
    import run_metrics

    assert run_metrics.main([]) == 2
    assert "медиана и разброс" in capsys.readouterr().out


def test_run_metrics_counts_slides_with_a_wide_empty_zone(tmp_path: Path) -> None:
    """C7. Целевая метрика B8 считается по колоде, а не по находкам.

    Находка есть только у слайда за порогом, и по находкам не видно, стала колода лучше
    или просто не дошла до порога.
    """
    import run_metrics

    run = write_run(
        tmp_path,
        "cccc",
        design_metrics={
            # Половина слайда пуста рядом с содержанием — это дыра.
            "s01": {"ink": 0.02, "imbalance": 2.4, "zone_w": 0.55, "zone_h": 1.0, "chrome": 1.0},
            # Воздух над рядом показателей: широко, но низко — не дыра.
            "s02": {"ink": 0.03, "imbalance": 0.6, "zone_w": 1.0, "zone_h": 0.32, "chrome": 1.0},
            "s03": {"ink": 0.04, "imbalance": 0.4, "zone_w": 0.2, "zone_h": 0.3, "chrome": 1.0},
            "s04": {"ink": 0.05, "imbalance": 0.3, "zone_w": 0.1, "zone_h": 0.2, "chrome": 1.0},
        },
    )
    values = run_metrics.metrics(run)

    assert values["слайдов с пустой зоной, %"] == 25.0
    assert values["дисбаланс (медиана)"] == 0.5
    assert "без превью макетов, слайдов" not in values


def test_run_metrics_says_when_the_layout_previews_were_missing(tmp_path: Path) -> None:
    """Без превью макетов метрики считают декор шаблона содержанием (C9).

    Такой прогон с прогоном, где превью были, сравнивать нельзя, и сводка обязана
    об этом сказать, а не молча смешать два разных замера.
    """
    import run_metrics

    run = write_run(
        tmp_path,
        "dddd",
        design_metrics={
            "s01": {"ink": 0.02, "imbalance": 0.4, "zone_w": 0.2, "zone_h": 0.2, "chrome": 0.0},
            "s02": {"ink": 0.03, "imbalance": 0.5, "zone_w": 0.2, "zone_h": 0.2, "chrome": 1.0},
        },
    )

    assert run_metrics.metrics(run)["без превью макетов, слайдов"] == 1.0


def test_run_metrics_survives_a_run_without_design_metrics(tmp_path: Path) -> None:
    """Прогоны до C7 отчёта с метриками не содержат: сводка молчит, а не падает."""
    import run_metrics

    assert "дисбаланс (медиана)" not in run_metrics.metrics(write_run(tmp_path, "eeee"))
