"""План даёт слайду заметку докладчика. Change `the-speaker-gets-a-note`, таск RG34
(`docs/agents/tasks-25-09.md`).

Поле `speaker_note` проложено сквозь весь конвейер — план, IR, писатель, html, фиксы,
схемы ответа — а в трёх `deck.pptx` 24.09 частей `notesSlide` 0, 0, 0: ни один промпт
заметку не просил. Правка — абзац в промпте планировщика (`deck_planner@1.3.0`);
здесь проверяется, что он на месте, что схема ответа не поменялась и что заметка плана
доезжает до `deck.pptx` и `deck.html`.

Сценарии — из дельты `openspec/changes/the-speaker-gets-a-note/specs/deck-planning/`.
Качество самой заметки и числа в ней — на живом прогоне: подделка модели здесь пишет
заметку сама.
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation

from deckforge.config import PROMPTS_DIR, RunConfig
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.parsing import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.run import collect_content_paths, generate_variant, load_brief
from deckforge.planning.planner import DeckPlanner
from deckforge.registry import get_prompt_registry, load_variant_profiles
from tests.integration.test_native_objects import build_template
from tests.integration.test_pipeline_end_to_end import FakeInference, theme_fonts
from tests.unit.test_planning import PRODUCT_FRAME, FakeLlm, payload_for

NOTE_RULE = "заметка — не пересказ"


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.fixture
def content() -> ContentPackage:
    """Своя фикстура, а не импорт из `test_planning`: ruff CI падает на F811."""
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[
            Fact(fact_id="f001", text="Выручка выросла на 37,5 %"),
            Fact(fact_id="f002", text="Клиентов стало более 500"),
        ],
    )


# --- промпт ------------------------------------------------------------------------------


def test_the_active_planner_asks_for_a_speaker_note() -> None:
    """Активная версия просит заметку — какой бы номер у неё ни был.

    Номер здесь был закреплён на `1.3.0` и покраснел на `1.3.1` (RG44), хотя правило
    никуда не делось. Тест, привязанный к номеру, проверяет реестр, а не поведение,
    и краснеет на каждой соседней правке промпта — так уже было в #154.
    """
    bundle = get_prompt_registry().load("deck_planner")

    assert "speaker_note" in bundle.system_template
    assert NOTE_RULE in bundle.system_template
    assert "speaker_note" in bundle.user_template, "в самопроверке задания пункта нет"


def test_the_previous_planner_did_not_ask_for_it() -> None:
    """Нарушитель: в 1.2.0 поле есть только в схеме, и модель честно оставляла `null`."""
    previous = (PROMPTS_DIR / "deck_planner" / "1.2.0" / "system.j2").read_text(encoding="utf-8")
    assert "speaker_note" not in previous


def test_the_response_schema_did_not_change() -> None:
    """Поле уже было в схеме ответа: просьбу меняем, контракт — нет.

    Сверяется с активной версией, а не с номером: каждая следующая правка промпта
    обязана оставлять схему ответа прежней, иначе это смена контракта, а не промпта.
    """
    bundle = get_prompt_registry().load("deck_planner")
    old = (PROMPTS_DIR / "deck_planner" / "1.2.0" / "schema.json").read_text(encoding="utf-8")
    new = (
        PROMPTS_DIR / "deck_planner" / bundle.version / "schema.json"
    ).read_text(encoding="utf-8")
    assert old == new
    assert "speaker_note" in new


def test_the_rule_names_what_a_note_carries_and_the_numbers_rule() -> None:
    system = get_prompt_registry().load("deck_planner").system_template
    rule = system[system.index("11. `speaker_note`") :]
    rule = rule[: rule.index("## Как писать")]

    for sign in ("вопрос", "связать", "правилу 3", "пустым"):
        assert sign in rule, f"в правиле 11 нет «{sign}»"


def test_the_planner_prompt_renders_with_the_rule(
    content: ContentPackage, manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """1.3.0 рендерится на тех же входах, что 1.2.0, и правило доходит до модели."""
    llm = FakeLlm(payload_for(PRODUCT_FRAME))
    asyncio.run(DeckPlanner(llm).plan(content, manifest, variant_a, seed=1))

    assert NOTE_RULE in llm.prompt_text


# --- заметка доезжает до файла ---------------------------------------------------------


NOTED = {
    "s02": "Сказать вслух: рост выручки держится на 37,5 % за год.",
    "s03": "Ожидать вопрос о клиентах — ответ: их более 500.",
}


class NotingInference(FakeInference):
    """Подделка сквозного прогона, у которой план несёт заметки двум слайдам."""

    def _plan(self) -> dict[str, Any]:
        plan = super()._plan()
        for slide in plan["slides"]:
            slide["speaker_note"] = NOTED.get(slide["slide_id"])
        return plan


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "факты.md").write_text(
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
        "content": content_dir,
        "brief": brief,
        "root": tmp_path,
    }


async def test_notes_of_the_plan_reach_the_pptx_and_the_html(
    workspace: dict[str, Path],
) -> None:
    root = workspace["root"]
    manifest = TemplateParser(cache_dir=root / "cache").parse(workspace["template"])
    out_dir = root / "artifacts" / "A"
    deps = Deps(
        brief=load_brief(workspace["brief"]),
        run=RunConfig(exports=["pptx", "html"], audit={"run_semantic": False, "auto_fix": False}),
        out_dir=out_dir,
        llm=NotingInference(manifest),
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
        run_id="notes",
    )

    notes = {s.slide_id: s.speaker_note for s in result.state["deck"].slides if s.speaker_note}
    assert notes == NOTED, "заметка плана потерялась по дороге к IR"

    pptx = result.exports["pptx"]
    with zipfile.ZipFile(pptx) as package:
        parts = [
            name
            for name in package.namelist()
            if name.startswith("ppt/notesSlides/") and name.endswith(".xml")
        ]
    assert len(parts) == len(NOTED), f"частей notesSlide {len(parts)}, а заметок {len(NOTED)}"
    written = {
        slide.notes_slide.notes_text_frame.text
        for slide in Presentation(str(pptx)).slides
        if slide.has_notes_slide
    }
    assert written == set(NOTED.values())

    html = result.exports["html"].read_text(encoding="utf-8")
    assert html.count('<aside class="notes" hidden>') == len(NOTED)
