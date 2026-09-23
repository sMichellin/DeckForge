"""Цитата и callout в IR (DG4, change `ir-callout-and-quote`).

Контракт заводится раньше рендера (DG3), чтобы потоки не ждали друг друга. Отсюда
три обязательства этого change:

* контракт строгий: `tone` — закрытое перечисление, цвет — только слот темы (правило 5);
* колода без новых блоков и старые чекпойнты читаются как прежде;
* модель не может заказать блок, который рендер ещё не рисует, — его нет в схеме
  ответа композитора; а если такой блок всё же оказался в IR, конвейер не падает
  и не теряет его молча.

С `compose-by-the-design-system` (DG3) рендер цитату и callout рисует, и исключение
из схемы ответа снято: проверки «вида нет в схеме ответа» заменены обратными
в `tests/unit/test_compose_by_the_design_system.py`. Здесь остался механизм исключения
(`test_the_exclusion_would_catch_a_leak`) — он ждёт следующего такого вида.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import Runtime
from pydantic import TypeAdapter, ValidationError

from deckforge.config import PROMPTS_DIR, load_yaml
from deckforge.domain.enums import CalloutTone, ColorRef
from deckforge.domain.slide import (
    Block,
    CalloutBlock,
    DeckIR,
    QuoteBlock,
    SlideIR,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from deckforge.pipeline.nodes.audit import audit_node  # noqa: E402
from deckforge.pipeline.nodes.export import export_node  # noqa: E402
from deckforge.pipeline.nodes.fit import fit_node  # noqa: E402
from deckforge.pipeline.nodes.render import render_node  # noqa: E402
from gen_schemas import response_schema  # noqa: E402
from tests.integration.test_native_objects import build_template  # noqa: E402
from tests.integration.test_pipeline_end_to_end import run_pipeline  # noqa: E402

NEW_TYPES = {"quote", "callout"}
BLOCK = TypeAdapter(Block)


def contract(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))


def block_kinds(schema: dict[str, Any]) -> set[str]:
    """Виды блоков, которые схема разрешает в `SlideIR.blocks` (у колоды — во вложенном)."""
    has_blocks = "blocks" in schema.get("properties", {})
    node = schema if has_blocks else schema["$defs"]["SlideIR"]
    return set(node["properties"]["blocks"]["items"]["discriminator"]["mapping"])


# --- контракт: норма ---------------------------------------------------------


def test_quote_is_a_block_of_the_ir() -> None:
    block = BLOCK.validate_python(
        {"block_id": "q", "type": "quote", "text": "Шаблон — это язык.", "author": "Заказчица",
         "accent_ref": "accent2"}
    )
    assert isinstance(block, QuoteBlock)
    assert block.accent_ref is ColorRef.ACCENT2
    assert block.bbox is None, "координаты у цитаты ставит вёрстка, а не модель"


def test_callout_is_a_block_of_the_ir() -> None:
    for tone in ("insight", "risk"):
        block = BLOCK.validate_python(
            {"block_id": "c", "type": "callout", "text": "Срок под угрозой", "tone": tone}
        )
        assert isinstance(block, CalloutBlock)
        assert block.tone is CalloutTone(tone)


def test_author_and_accent_are_optional() -> None:
    quote = QuoteBlock(block_id="q", text="Без подписи")
    assert quote.author is None and quote.accent_ref is None


def test_new_blocks_carry_no_font_size() -> None:
    """Правило 6: кегль — из шкалы шаблона, модель его не задаёт."""
    for model in (QuoteBlock, CalloutBlock):
        assert "size_pt" not in model.model_fields


# --- контракт: нарушители ----------------------------------------------------


@pytest.mark.parametrize("tone", ["warning", "INSIGHT", "", "note"])
def test_tone_outside_the_enum_is_rejected(tone: str) -> None:
    with pytest.raises(ValidationError):
        BLOCK.validate_python({"block_id": "c", "type": "callout", "text": "т", "tone": tone})


def test_callout_without_tone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BLOCK.validate_python({"block_id": "c", "type": "callout", "text": "т"})


@pytest.mark.parametrize("kind", ["quote", "callout"])
@pytest.mark.parametrize("color", ["#E4002B", "#e4002b", "E4002B", "red"])
def test_rgb_literal_is_not_a_valid_accent_ref(kind: str, color: str) -> None:
    """Правило 5: цвет в IR — имя слота темы, `#RRGGBB` отвергается схемой."""
    payload: dict[str, Any] = {"block_id": "b", "type": kind, "text": "т", "accent_ref": color}
    if kind == "callout":
        payload["tone"] = "risk"
    with pytest.raises(ValidationError):
        BLOCK.validate_python(payload)


@pytest.mark.parametrize("kind", ["quote", "callout"])
def test_empty_text_is_rejected(kind: str) -> None:
    payload: dict[str, Any] = {"block_id": "b", "type": kind, "text": ""}
    if kind == "callout":
        payload["tone"] = "insight"
    with pytest.raises(ValidationError):
        BLOCK.validate_python(payload)


def test_contract_schema_forbids_rgb_in_accent_ref() -> None:
    for name in ("QuoteBlock", "CalloutBlock"):
        accent = contract("slide_ir")["$defs"][name]["properties"]["accent_ref"]
        refs = {branch.get("$ref") for branch in accent["anyOf"]}
        assert "#/$defs/ColorRef" in refs
        assert not any("pattern" in branch for branch in accent["anyOf"])
    assert set(contract("slide_ir")["$defs"]["CalloutTone"]["enum"]) == {"insight", "risk"}


# --- обратная совместимость --------------------------------------------------


def deck_without_new_blocks() -> dict[str, Any]:
    """Колода в том виде, в каком её писала прежняя композиция: без новых полей."""
    return {
        "deck_id": "d1",
        "variant": "A",
        "template_id": "t1",
        "seed": 1,
        "slides": [
            {
                "slide_id": "s01",
                "layout_id": "L01",
                "variant": "A",
                "blocks": [
                    {"block_id": "t", "type": "text", "placeholder_idx": 0,
                     "role": "title", "text": "Выручка выросла"},
                    {"block_id": "b", "type": "bullets", "placeholder_idx": 1,
                     "items": [{"text": "Клиентов больше 500"}]},
                    {"block_id": "k", "type": "kpi", "x": 1, "y": 1, "cx": 10, "cy": 10,
                     "items": [{"value": "37,5 %", "label": "рост"}]},
                ],
                "fit_report": {"t": {"final_size_pt": 32}},
            }
        ],
    }


def test_deck_without_new_blocks_validates_as_before() -> None:
    raw = deck_without_new_blocks()
    deck = DeckIR.model_validate(raw)
    assert [b.type for b in deck.slides[0].blocks] == ["text", "bullets", "kpi"]
    # Туда и обратно — без потерь: так чекпойнт колоды пишется и читается.
    assert DeckIR.model_validate_json(deck.model_dump_json()) == deck


def test_old_block_kinds_are_all_still_in_the_contract() -> None:
    kinds = block_kinds(contract("slide_ir"))
    assert kinds == {
        "text", "bullets", "chart", "table", "smartart", "icon", "image", "kpi", *NEW_TYPES
    }
    assert kinds == block_kinds(contract("deck_ir"))


# --- схема ответа композитора ------------------------------------------------


def test_new_blocks_are_in_the_golden_contract() -> None:
    for name in ("slide_ir", "deck_ir"):
        schema = contract(name)
        assert block_kinds(schema) >= NEW_TYPES, name
        assert {"QuoteBlock", "CalloutBlock", "CalloutTone"} <= set(schema["$defs"]), name


def test_the_exclusion_would_catch_a_leak() -> None:
    """Страховка от теста, который зелен потому, что ничего не проверяет: без
    исключения генератор выдал бы новые виды модели. С DG3 список исключений пуст —
    механизм проверяется на тех же двух видах, переданных явно."""
    omit = frozenset(load_yaml(PROMPTS_DIR / "slide_composer" / "1.2.0" / "meta.yaml")[
        "response_omit"
    ])
    leaked, dropped = response_schema(SlideIR, omit, withheld=frozenset())
    kept, dropped_kept = response_schema(SlideIR, omit, withheld=frozenset(NEW_TYPES))
    assert block_kinds(json.loads(leaked)) >= NEW_TYPES
    assert not NEW_TYPES & block_kinds(json.loads(kept))
    assert {"блок quote", "блок callout"} <= dropped_kept
    assert not {"блок quote", "блок callout"} & dropped


# --- конвейер с новым блоком в IR --------------------------------------------


def workspace(root: Path) -> dict[str, Path]:
    """Шаблон python-pptx и один факт — как в сквозном тесте конвейера (C6)."""
    content = root / "content"
    content.mkdir()
    (content / "факты.md").write_text(
        "# Итоги года\n\nВыручка выросла на 37,5 % за год.\n", encoding="utf-8"
    )
    brief = root / "brief.yaml"
    brief.write_text(
        "purpose: product\naudience: правление\ntarget_slides: 6\nlanguage: ru\n",
        encoding="utf-8",
    )
    template = build_template(root / "template.pptx")
    return {"template": template, "content": content, "brief": brief, "root": root}


def slide_with_new_blocks(slide: SlideIR, box: Any) -> SlideIR:
    """Слайд прогона плюс цитата и callout в нижней четверти поля контента."""
    quarter = box.cy // 4
    y = box.y + box.cy - quarter
    half = box.cx // 2
    extra: list[Block] = [
        QuoteBlock(block_id="dg4q", text="Шаблон задаёт язык колоды", author="Бриф",
                   accent_ref=ColorRef.ACCENT1, x=box.x, y=y, cx=half, cy=quarter),
        CalloutBlock(block_id="dg4c", text="Срок сдачи под угрозой", tone=CalloutTone.RISK,
                     x=box.x + half, y=y, cx=box.cx - half, cy=quarter),
    ]
    return slide.model_copy(update={"blocks": [*slide.blocks, *extra]})


async def run_nodes_after_compose(
    tmp_path: Path, with_new_blocks: bool
) -> tuple[dict[str, Any], list[str]]:
    """Прогон графа, затем вписывание, рендер, аудит и экспорт заново — по колоде,
    в которую цитата и callout положены мимо модели (чекпойнт, правка)."""
    result, deps = await run_pipeline(workspace(tmp_path))
    state: dict[str, Any] = dict(result.state)
    box = state["manifest"].content_bbox
    slides = state["deck"].slides
    state["slides"] = [slide_with_new_blocks(s, box) for s in slides] if with_new_blocks else slides
    runtime = Runtime(context=deps)

    notes: list[str] = []
    for node in (fit_node, render_node, audit_node, export_node):
        update = await node(state, runtime)  # type: ignore[arg-type]
        notes += [*update.get("notes", []), *update.get("errors", [])]
        state.update({k: v for k, v in update.items() if k not in ("notes", "errors")})
    return state, notes


@pytest.mark.cold
async def test_pipeline_survives_new_blocks_in_the_ir(tmp_path: Path) -> None:
    """Нарушитель: новый блок в IR проходит вписывание, рендер, аудит и экспорт —
    не исключение и не молчаливая потеря. С DG3 (`draw-by-the-design-system`) рендер
    его рисует, и заметки «не нарисован» больше нет: рисунок проверяет
    `tests/unit/test_draw_by_the_design_system.py`."""
    state, notes = await run_nodes_after_compose(tmp_path, with_new_blocks=True)

    deck: DeckIR = state["deck"]
    for slide in deck.slides:
        assert {"dg4q", "dg4c"} <= {b.block_id for b in slide.blocks}, (
            "новый блок выпал из колоды молча"
        )
        assert {"dg4q", "dg4c"} <= set(slide.fit_report), "новый блок не вписан"
    assert not [note for note in notes if "не нарисован" in note], notes
    assert state["pptx_path"].is_file()
    assert state["exports"]["html"].is_file()
    assert state["audit"].summary.passed + len(state["audit"].findings) > 0


@pytest.mark.cold
async def test_deck_without_new_blocks_gets_no_such_note(tmp_path: Path) -> None:
    """Норма: заметка о пропуске не появляется там, где пропускать нечего."""
    _, notes = await run_nodes_after_compose(tmp_path, with_new_blocks=False)
    assert not [note for note in notes if "не нарисован" in note]


@pytest.mark.cold
async def test_model_that_sends_a_quote_anyway_is_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Модель прислала цитату и callout. До DG3 их не было в схеме ответа, и композитор
    отбрасывал их с заметкой; с `compose-by-the-design-system` они — свободные блоки:
    ставятся решателем, не теряются и не роняют прогон."""
    import tests.integration.test_pipeline_end_to_end as e2e

    original = e2e.FakeInference._slide

    def with_quote(self: Any) -> dict[str, Any]:
        payload = original(self)
        payload["blocks"] += [
            {"block_id": "q", "type": "quote", "text": "Шаблон задаёт язык колоды"},
            {"block_id": "c", "type": "callout", "text": "Срок под угрозой", "tone": "risk"},
        ]
        return payload

    monkeypatch.setattr(e2e.FakeInference, "_slide", with_quote)
    result, _ = await run_pipeline(workspace(tmp_path))

    assert not result.interrupted
    assert result.exports["pptx"].is_file()
    notes = result.state.get("notes") or []
    for block_id, kind in (("q", "quote"), ("c", "callout")):
        assert not any(f"блок {block_id} ({kind}) отброшен" in note for note in notes), notes
    for slide in result.state["deck"].slides:
        assert {"q", "c"} <= {block.block_id for block in slide.blocks}
