"""Число слайдов на выбор: задать или подобрать. Change `slides-count-by-choice`, Т1
(`docs/agents/requirements-from-notes-26-09.md`).

Заметка 26.09: «Необходимо сделать на выбор: можно выбрать количество слайдов итоговой
презентации, или нейронка сама подбирает оптимальное». Раньше число было обязательным,
работало потолком, а причина, по которой слайдов стало меньше, видна была только
в заметках `run.json`.

Сценарии — из дельты `openspec/changes/slides-count-by-choice/specs/deck-planning/`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deckforge.api.jobs import _slides
from deckforge.api.schemas import RunRequest
from deckforge.config import RunConfig
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.template import TemplateManifest
from deckforge.parsing import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.run import collect_content_paths, generate_variant, load_brief
from deckforge.planning.planner import AUTO_MAX_SLIDES, DeckPlanner, decide_slides
from deckforge.registry import load_variant_profiles
from tests.integration.test_native_objects import build_template
from tests.integration.test_pipeline_end_to_end import FakeInference, theme_fonts
from tests.unit.test_planning import PRODUCT_FRAME, FakeLlm, payload_for


def pack(facts: int, target: int | None = 12) -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=target),
        facts=[Fact(fact_id=f"f{i:03d}", text=f"Факт номер {i}") for i in range(1, facts + 1)],
    )


FRAME = len(PRODUCT_FRAME)


# --- решение -----------------------------------------------------------------------------


def test_an_exact_count_is_kept_when_the_material_holds_it() -> None:
    decision = decide_slides(pack(60, target=12), "product", 12)
    assert (decision.mode, decision.count) == ("exact", 12)
    assert "как задано" in decision.reason


def test_an_exact_count_on_thin_material_is_cut_with_a_reason() -> None:
    """Нарушитель прежнего поведения: урезалось, а в интерфейсе причины не было."""
    decision = decide_slides(pack(12, target=12), "product", 12)
    assert decision.count < 12
    assert "задано 12" in decision.reason and "12 фактов" in decision.reason


def test_the_frame_of_the_purpose_holds_the_bottom() -> None:
    decision = decide_slides(pack(60, target=2), "product", 2)
    assert decision.count == FRAME and "каркас" in decision.reason


def test_auto_counts_by_the_material() -> None:
    decision = decide_slides(pack(24, target=None), "product", None)
    assert decision.mode == "auto" and decision.requested is None
    assert decision.count == 24 // 3 + 2
    assert decision.reason.startswith("подобрано автоматически")


def test_auto_stops_at_the_top_of_the_brief_range() -> None:
    decision = decide_slides(pack(90, target=None), "product", None)
    assert decision.count == AUTO_MAX_SLIDES
    assert str(AUTO_MAX_SLIDES) in decision.reason


def test_auto_on_thin_material_is_not_padded_below_the_frame() -> None:
    decision = decide_slides(pack(3, target=None), "product", None)
    assert decision.count == FRAME


# --- бриф, промпт, API, интерфейс -------------------------------------------------------


def test_a_brief_without_a_count_means_auto() -> None:
    assert Brief(purpose="product", audience="правление").target_slides is None


def test_the_planner_names_a_number_not_none(
    manifest: TemplateManifest,
) -> None:
    """Промпт «добирай до None штук» модель прочла бы как угодно."""
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    content = pack(24, target=None)
    asyncio.run(DeckPlanner(llm).plan(content, manifest, load_variant_profiles()["A"], seed=1))

    assert "None" not in llm.prompt_text
    assert f"до {24 // 3 + 2} штук" in llm.prompt_text


def test_the_api_takes_null_as_auto() -> None:
    assert RunRequest(target_slides=None).target_slides is None
    assert _slides(None) is None and _slides(8) == 8


def test_the_ui_sends_none_in_auto_mode() -> None:
    from frontend.app import SLIDES_AUTO, SLIDES_EXACT, chosen_slides

    assert chosen_slides({"slides_mode": SLIDES_AUTO, "target_slides": 12}) is None
    assert chosen_slides({"slides_mode": SLIDES_EXACT, "target_slides": 8}) == 8


# --- отчёт -------------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    content = tmp_path / "content"
    content.mkdir()
    (content / "факты.md").write_text(
        "# Итоги года\n\nВыручка выросла на 37,5 % за год.\n\nКлиентов стало более 500.\n",
        encoding="utf-8",
    )
    brief = tmp_path / "brief.yaml"
    brief.write_text("purpose: product\naudience: правление\nlanguage: ru\n", encoding="utf-8")
    return {
        "template": build_template(tmp_path / "template.pptx"),
        "content": content,
        "brief": brief,
        "root": tmp_path,
    }


async def test_the_run_report_names_the_decision(workspace: dict[str, Path]) -> None:
    """Бриф без числа — автоматический режим, и отчёт говорит, сколько и почему."""
    root = workspace["root"]
    manifest = TemplateParser(cache_dir=root / "cache").parse(workspace["template"])
    out_dir = root / "out"
    deps = Deps(
        brief=load_brief(workspace["brief"]),
        run=RunConfig(exports=["pptx"], audit={"run_semantic": False, "auto_fix": False}),
        out_dir=out_dir,
        llm=FakeInference(manifest),
        fonts=theme_fonts(root, manifest),
        cache_dir=root / "cache",
        work_dir=out_dir,
    )
    result = await generate_variant(
        workspace["template"],
        collect_content_paths(workspace["content"]),
        load_variant_profiles()["A"],
        deps,
        seed=1337,
        run_id="slides-auto",
    )

    report = json.loads(result.write_report().read_text(encoding="utf-8"))
    decision = report["slides_decision"]
    assert decision["mode"] == "auto" and decision["requested"] is None
    assert decision["planned"] == report["planned_slides"]
    assert decision["reason"].startswith("подобрано автоматически")
