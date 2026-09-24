"""Композиция по дизайн-системе шаблона. Change `compose-by-the-design-system` (DG3, часть 2).

Что проверяется:

* контракт стилей списка (решение тимлида 1): `BulletsBlock.style` и `BulletItem.icon`
  необязательны, старые колоды и чекпойнты валидны без правок;
* вёрстка рисует три стиля параметрами дизайн-системы: номер — автонумерация цветом
  акцента по роли, иконка — нативная фигура по первой строке пункта, отбивка — шаг ДС;
  промежуток между свободными блоками — шаг `grid.spacing` ДС;
* композиция: цитата и callout — свободные блоки, цвет модели сверяется с ролями ДС,
  стиль списка сводится с тем, что вёрстка нарисует, у отброса — своя причина;
  активный промпт `slide_composer@1.3.0` получает роли и виды, а не координаты;
* аудит (решение тимлида 2): текст цитаты и callout сверяется с материалами;
* холодный шаблон (правило 10): ролей нет — акцент по порядку слотов, как прежде.

Шаблоны — синтетический манифест `conftest` и стандартный шаблон python-pptx: ни один
не похож на шаблоны кейса (C6).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pydantic import ValidationError

from deckforge.audit.geometry import block_text, carries_text
from deckforge.audit.semantic.grounding import numbers_grounded
from deckforge.composition.composer import SlideComposer, _why_not_free
from deckforge.config import PROMPTS_DIR
from deckforge.designsystem import DesignSystem, derive
from deckforge.domain.base import BBox
from deckforge.domain.content import Asset, Brief, ContentPackage, Fact, Number
from deckforge.domain.enums import (
    CalloutTone,
    ChartType,
    ColorRef,
    ListStyle,
    SlideIntent,
    TextRole,
)
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    CalloutBlock,
    ChartBlock,
    DeckIR,
    KpiBlock,
    QuoteBlock,
    SlideIR,
)
from deckforge.domain.template import TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.domain.variants import VariantProfile
from deckforge.export.html import export_html
from deckforge.inference.client import Completion
from deckforge.layout.by_design import MAX_INSET_SHARE, DesignRules
from deckforge.layout.constraints import solve_positions
from deckforge.layout.fitting import fit_icon_list, fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.lists import icon_column, icon_text_frame
from deckforge.layout.metrics import measure_text
from deckforge.parsing import TemplateParser
from deckforge.registry import get_prompt_registry, load_variant_profiles
from deckforge.rendering.writer import PptxWriter
from tests.integration.test_native_objects import build_template
from tests.unit._audit_builders import context_for
from tests.unit._audit_builders import deck as audit_deck
from tests.unit._audit_builders import slide as audit_slide
from tests.unit._audit_builders import title as audit_title
from tests.unit.test_draw_by_the_design_system import accent_role, slide_with, with_roles
from tests.unit.test_layout_fonts import make_font

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from gen_schemas import WITHHELD_BLOCK_TYPES  # noqa: E402


def contract(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))


# --- контракт: стиль списка и иконка пункта --------------------------------------


def old_checkpoint() -> dict[str, Any]:
    """Колода в том виде, в каком её писала композиция до этого change: без новых полей."""
    return {
        "deck_id": "d1",
        "variant": "A",
        "template_id": "t1",
        "seed": 1,
        "slides": [
            {
                "slide_id": "s01",
                "layout_id": "L07",
                "variant": "A",
                "blocks": [
                    {"block_id": "t", "type": "text", "placeholder_idx": 0,
                     "role": "title", "text": "Выручка выросла"},
                    {"block_id": "b", "type": "bullets", "placeholder_idx": 1,
                     "items": [{"text": "Клиентов больше 500", "level": 0}],
                     "max_level": 1},
                    {"block_id": "q", "type": "quote", "x": 1, "y": 1, "cx": 10, "cy": 10,
                     "text": "Шаблон задаёт язык колоды"},
                ],
                "fit_report": {"t": {"final_size_pt": 32}},
            }
        ],
    }


def test_an_old_checkpoint_validates_without_edits() -> None:
    """Норма: чекпойнт прежней композиции читается, список — маркированный, как был."""
    deck = DeckIR.model_validate(old_checkpoint())
    bullets = deck.slides[0].blocks[1]
    assert isinstance(bullets, BulletsBlock)
    assert bullets.style is None
    assert bullets.items[0].icon is None
    assert DeckIR.model_validate_json(deck.model_dump_json()) == deck


def test_the_three_list_styles_are_the_contract() -> None:
    assert {style.value for style in ListStyle} == {"bulleted", "numbered", "icon"}
    for name in ("slide_ir", "deck_ir"):
        schema = contract(name)
        assert set(schema["$defs"]["ListStyle"]["enum"]) == {"bulleted", "numbered", "icon"}
        assert "style" in schema["$defs"]["BulletsBlock"]["properties"]
        assert "icon" in schema["$defs"]["BulletItem"]["properties"]
        assert "style" not in schema["$defs"]["BulletsBlock"].get("required", [])


def test_an_icon_list_is_valid() -> None:
    block = BulletsBlock(
        block_id="b",
        style=ListStyle.ICON,
        items=[BulletItem(text="Защищено", icon="shield-check"), BulletItem(text="Растёт",
                                                                           icon="trending-up")],
    )
    assert block.style is ListStyle.ICON
    assert [item.icon for item in block.items] == ["shield-check", "trending-up"]


@pytest.mark.parametrize(
    "icon",
    ["assets/icons/shield.svg", "shield.svg", "#E03131", "Shield Check", "C:\\icons\\x", ""],
)
def test_an_icon_is_a_name_not_a_path_or_a_color(icon: str) -> None:
    """Нарушитель: путь, файл, цвет и имя с пробелом иконкой не бывают."""
    with pytest.raises(ValidationError):
        BulletItem(text="Пункт", icon=icon)


def test_a_style_outside_the_set_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BulletsBlock.model_validate(
            {"block_id": "b", "style": "checklist", "items": [{"text": "Пункт"}]}
        )


# --- вёрстка: три стиля списка --------------------------------------------------


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    directory = tmp_path / "fonts"
    directory.mkdir()
    make_font(directory, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(directory, manifest.theme.fonts.minor_latin, advance=500)
    make_font(directory, manifest.theme.fonts.minor_latin, advance=550, bold=True)
    return FontLibrary([directory])


@pytest.fixture
def real(tmp_path: Path) -> tuple[Path, TemplateManifest]:
    template = build_template(tmp_path / "template.pptx")
    return template, TemplateParser(cache_dir=tmp_path / "cache").parse(template)


ICONS = ("target", "trending-up", "shield-check")
ITEMS = ("Цель пилота — сократить срок", "Выручка растёт", "Данные защищены")


def listing(
    style: ListStyle | None = None,
    *,
    icons: tuple[str | None, ...] = ICONS,
    placeholder: int | None = None,
) -> BulletsBlock:
    return BulletsBlock(
        block_id="b",
        style=style,
        placeholder_idx=placeholder,
        items=[BulletItem(text=text, icon=icon) for text, icon in zip(ITEMS, icons, strict=True)],
    )


def written(
    tmp_path: Path,
    template: Path,
    manifest: TemplateManifest,
    slide: SlideIR,
    design: DesignSystem | None = None,
) -> tuple[Path, SlideIR, list[str]]:
    fitted = fit_slide(slide, manifest, design=DesignRules(manifest, design))
    deck = DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=[fitted])
    writer = PptxWriter(template, manifest, design_system=design)
    out = writer.write(deck, tmp_path / "d.pptx")
    return out, fitted, writer.degradations


def xml_of(path: Path) -> str:
    slide = Presentation(str(path)).slides[0]
    return "".join(shape._element.xml for shape in slide.shapes)


def body_layout(manifest: TemplateManifest) -> tuple[str, int]:
    layout = next(
        spec for spec in manifest.layouts
        if any(ph.role is TextRole.BODY for ph in spec.placeholders)
    )
    body = next(ph for ph in layout.placeholders if ph.role is TextRole.BODY)
    return layout.layout_id, body.idx


def icon_group(path: Path) -> Any:
    slide = Presentation(str(path)).slides[0]
    found = [shape for shape in slide.shapes
             if shape.shape_type == MSO_SHAPE_TYPE.GROUP and shape.name == "Иконочный список"]
    return found[0] if found else None


def test_a_numbered_list_is_numbered_by_powerpoint_in_the_role_accent(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    """Номер — автонумерация PowerPoint (текст пункта не трогается), цвет номера —
    акцент по роли ДС слотом темы, а не `accent1` и не RGB."""
    template, manifest = real
    design = with_roles(manifest, accent_role(manifest, ColorRef.ACCENT4, 0.3))
    path, _, _ = written(tmp_path, template, manifest,
                         slide_with(manifest, listing(ListStyle.NUMBERED)), design)

    xml = xml_of(path)
    assert xml.count('buAutoNum type="arabicPeriod"') == 3
    assert "accent4" in xml and "srgbClr" not in xml
    assert "1. Цель" not in xml, "номер вписан в текст, а не нумерацией"


def test_a_list_without_a_style_keeps_the_template_marker(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    """Норма: список без стиля — прежний маркированный, нумерации и иконок нет."""
    template, manifest = real
    path, _, _ = written(tmp_path, template, manifest, slide_with(manifest, listing()))
    xml = xml_of(path)
    assert "buAutoNum" not in xml and "custGeom" not in xml
    assert ("buChar" in xml) == bool(manifest.bullet_levels)


def test_a_numbered_list_in_a_placeholder_is_numbered_too(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    template, manifest = real
    layout_id, idx = body_layout(manifest)
    slide = SlideIR(slide_id="s1", layout_id=layout_id, variant="A",
                    blocks=[listing(ListStyle.NUMBERED, placeholder=idx)])
    path, _, _ = written(tmp_path, template, manifest, slide)
    assert xml_of(path).count("buAutoNum") == 3


def test_an_icon_list_draws_an_icon_by_every_item(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    """Иконка — нативная фигура (C3) у каждого пункта, по первой строке, слева от текста;
    цвет — первый акцент темы; текст — одна рамка, уже рамки блока."""
    template, manifest = real
    design = with_roles(manifest, accent_role(manifest, ColorRef.ACCENT4, 0.3))
    path, fitted, _ = written(tmp_path, template, manifest,
                              slide_with(manifest, listing(ListStyle.ICON)), design)

    group = icon_group(path)
    assert group is not None
    icons = [shape for shape in group.shapes if shape.name.startswith("Иконка ")]
    texts = [shape for shape in group.shapes if shape.has_text_frame and shape.text_frame.text]
    assert [shape.name for shape in icons] == [f"Иконка {name}" for name in ICONS]
    assert len(texts) == 1
    assert texts[0].text_frame.text.split("\n") == list(ITEMS)
    tops = [shape.top for shape in icons]
    assert tops == sorted(tops) and len(set(tops)) == 3
    assert all(shape.left + shape.width <= texts[0].left for shape in icons)
    assert all("custGeom" in shape._element.xml for shape in icons)
    assert "accent1" in group._element.xml and "accent4" not in group._element.xml
    assert "srgbClr" not in group._element.xml
    block = fitted.block("b")
    assert block is not None and block.bbox is not None
    assert texts[0].width < block.bbox.cx


def test_an_icon_list_is_measured_without_the_icon_column(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Нарушитель прежнего вписывания: мерить иконочный список по всей рамке значит
    не заметить, что колонка иконок отняла у текста ширину."""
    rules = DesignRules(manifest)
    area = manifest.content_bbox
    box = BBox(x=area.x, y=area.y, cx=6 * EMU_PER_CM, cy=area.cy)
    block = listing(ListStyle.ICON).model_copy(
        update={"x": box.x, "y": box.y, "cx": box.cx, "cy": box.cy}
    )

    fit = fit_icon_list(block, box, manifest, rules, fonts=fonts)

    frame = icon_text_frame(box, icon_column(box, fit.final_size_pt, rules))
    step = manifest.typography(TextRole.BODY)
    assert step is not None and frame.cx < box.cx
    expected = measure_text(
        "\n".join(ITEMS), font_family=manifest.theme.fonts.minor_latin,
        size_pt=fit.final_size_pt, box=frame, line_spacing=step.line_spacing or 1.0,
        fonts=fonts,
    )
    assert fit.required_cy_emu == expected.height_emu
    assert fit.final_size_pt in manifest.size_ladder_pt


def test_the_icon_pad_is_the_design_system_step(manifest: TemplateManifest) -> None:
    """Отбивка иконки — шаг элемента `icon` ДС; шаг шире `MAX_INSET_SHARE` рамки делится."""
    rules = DesignRules(manifest)
    element = next(item for item in rules.ds.synthesized if item.kind == "icon")
    step = element.spacing_emu or 1
    assert rules.icon_pad_emu(100 * step) == step
    assert rules.icon_pad_emu(step) <= max(1, step * MAX_INSET_SHARE)


def test_an_icon_list_in_a_placeholder_keeps_the_template_marker(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    """В плейсхолдере абзацы верстает PowerPoint — иконку к строке не привязать."""
    template, manifest = real
    layout_id, idx = body_layout(manifest)
    slide = SlideIR(slide_id="s1", layout_id=layout_id, variant="A",
                    blocks=[listing(ListStyle.ICON, placeholder=idx)])
    path, _, _ = written(tmp_path, template, manifest, slide)
    assert icon_group(path) is None
    assert "custGeom" not in xml_of(path)


def test_an_unknown_icon_turns_the_list_into_bullets_with_a_note(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    """Нарушитель: иконки нет в наборе. Список с дырой не пишется — весь список
    маркированный, запись колоды не падает, подмена названа."""
    template, manifest = real
    block = listing(ListStyle.ICON, icons=("target", "no-such-icon-anywhere", "shield-check"))
    path, _, degradations = written(tmp_path, template, manifest, slide_with(manifest, block))

    assert icon_group(path) is None
    assert any(
        "иконочный список → маркированный" in note and "no-such-icon-anywhere" in note
        for note in degradations
    ), degradations


def test_html_draws_the_same_list_styles(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    _template, manifest = real
    design = with_roles(manifest, accent_role(manifest, ColorRef.ACCENT4, 0.3))
    numbered = listing(ListStyle.NUMBERED)
    icons = listing(ListStyle.ICON).model_copy(update={"block_id": "i"})
    fitted = fit_slide(slide_with(manifest, numbered, icons), manifest,
                       design=DesignRules(manifest, design))
    deck = DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=[fitted])

    html = export_html(deck, manifest, tmp_path / "d.html", design_system=design).read_text(
        encoding="utf-8"
    )

    assert 'class="numbered"' in html and "--marker: var(--accent4)" in html
    assert 'class="block bullets icon-list"' in html
    assert html.count('class="glyph"') == 3
    assert "#" not in html.split("</style>")[1].split("data:")[0].replace("#arrow", ""), (
        "литеральный цвет в разметке слайда"
    )


@pytest.mark.cold
def test_a_cold_template_draws_list_markers_in_accent1(
    tmp_path: Path, real: tuple[Path, TemplateManifest]
) -> None:
    """Правило 10: ролей нет — номер и иконки `accent1`, как у остальных блоков."""
    template, manifest = real
    cold = DesignRules(manifest).ds.model_copy(update={"palette_roles": []})
    rules = DesignRules(manifest, cold)
    assert rules.block_accent(None) is ColorRef.ACCENT1

    path, _, _ = written(tmp_path, template, manifest,
                         slide_with(manifest, listing(ListStyle.ICON)), cold)
    assert "accent1" in icon_group(path)._element.xml


# --- вёрстка: промежуток между свободными блоками -------------------------------


def gap_between(boxes: dict[str, BBox]) -> int:
    first, second = sorted(boxes.values(), key=lambda box: (box.x, box.y))
    return max(second.x - first.right, second.y - first.bottom)


def test_free_blocks_are_spaced_by_the_given_gap(manifest: TemplateManifest) -> None:
    gap = 2 * EMU_PER_CM
    assert gap_between(solve_positions([("a", None), ("b", None)], manifest, gap_emu=gap)) == gap


def test_the_gap_is_the_declared_gutter_when_the_grid_has_one(
    manifest: TemplateManifest,
) -> None:
    """Норма: шаг объявлен в сетке — промежуток прежний, `grid.gutter_emu`."""
    pair: list[tuple[str, BBox | None]] = [("a", None), ("b", None)]
    gap = DesignRules(manifest).block_gap_emu()
    assert manifest.grid.gutter_emu > 0
    assert gap == manifest.grid.gutter_emu
    assert solve_positions(pair, manifest) == solve_positions(pair, manifest, gap_emu=gap)


def test_a_grid_without_a_gutter_still_spaces_the_blocks(manifest: TemplateManifest) -> None:
    """Нарушитель прежнего правила: сетка без объявленного зазора ставила свободные
    блоки вплотную. Шаг ДС выводится из полей — и блоки разведены."""
    pair: list[tuple[str, BBox | None]] = [("a", None), ("b", None)]
    bare = manifest.model_copy(
        update={"grid": manifest.grid.model_copy(update={"gutter_emu": 0})}
    )
    assert gap_between(solve_positions(pair, bare)) == 0, "прежде — вплотную"

    gap = DesignRules(bare).block_gap_emu()
    assert gap > 0
    assert gap_between(solve_positions(pair, bare, gap_emu=gap)) == gap


# --- композиция: цитата, callout и причина отброса -------------------------------


class FakeLlm:
    model = "fake"

    def __init__(self, blocks: list[dict[str, Any]]) -> None:
        self.payload = {"blocks": blocks}
        self.prompt = ""

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        self.prompt = "\n".join(str(m.get("content", "")) for m in messages)
        return Completion(text=json.dumps(self.payload, ensure_ascii=False), model=self.model)


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[Fact(fact_id="f001", text="Выручка выросла на 37,5 % за год")],
    )


TITLE = {"block_id": "t", "type": "text", "placeholder_idx": 0, "role": "title",
         "text": "Выручка выросла"}


def plan() -> SlidePlan:
    return SlidePlan(slide_id="s02", intent=SlideIntent.PROBLEM,
                     headline="Выручка выросла", fact_refs=["f001"])


async def composed(
    blocks: list[dict[str, Any]],
    manifest: TemplateManifest,
    content: ContentPackage,
    variant: VariantProfile,
    design: DesignSystem | None = None,
    composer: SlideComposer | None = None,
) -> tuple[SlideIR, SlideComposer, FakeLlm]:
    llm = FakeLlm([TITLE, *blocks])
    composer = composer or SlideComposer(llm)
    composer.llm = llm
    ir = await composer.compose(plan(), content, manifest, variant, seed=7, design_system=design)
    return ir, composer, llm


async def test_quote_and_callout_are_placed_as_free_blocks(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Нарушитель прежней композиции: цитата и callout без плейсхолдера отбрасывались
    («ставить его свободно нельзя»). Теперь место им даёт решатель, внутри полей."""
    ir, composer, _ = await composed(
        [{"block_id": "q", "type": "quote", "text": "Шаблон задаёт язык колоды",
          "author": "Бриф"},
         {"block_id": "c", "type": "callout", "tone": "insight",
          "text": "Выручка выросла на 37,5 % за год"}],
        manifest, content, variant_a,
    )
    for block_id in ("q", "c"):
        block = ir.block(block_id)
        assert block is not None and block.bbox is not None, composer.notes
        assert manifest.content_bbox.contains(block.bbox)
    assert not [note for note in composer.notes if "отброшен" in note]


@pytest.mark.parametrize(
    ("block", "reason"),
    [
        ({"block_id": "x", "type": "icon", "query": "target"}, "одиночная иконка"),
        ({"block_id": "x", "type": "image", "source": "asset", "asset_ref": "a001"}, "картинке"),
    ],
)
async def test_a_dropped_block_names_its_own_reason(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile,
    block: dict[str, Any], reason: str,
) -> None:
    """Заметка об отбросе называет, чего не хватило этому виду, а не общую фразу."""
    content = content.model_copy(update={"assets": [
        Asset(asset_id="a001", kind="image", path="a.png")
    ]}) if block["type"] == "image" else content
    _, composer, _ = await composed([block], manifest, content, variant_a)

    dropped = [note for note in composer.notes if "блок x" in note and "отброшен" in note]
    assert dropped, composer.notes
    assert reason in dropped[0]
    assert "ставить его свободно нельзя" not in dropped[0]


def test_a_chart_without_a_layout_for_it_says_so(manifest: TemplateManifest) -> None:
    title_only = manifest.layouts[0]
    assert not title_only.capacity.supports_chart
    chart = ChartBlock(block_id="ch", chart_type=ChartType.LINE, dataset_ref="d")
    assert "capacity.supports_chart" in _why_not_free(chart, title_only)
    body = manifest.layouts[1]
    assert body.capacity.supports_chart
    assert "плейсхолдер" in _why_not_free(chart, body)


# --- композиция: цвет по роли ----------------------------------------------------


KPI = {"block_id": "k", "type": "kpi",
       "items": [{"value": "37,5 %", "label": "рост выручки", "color_ref": "accent1"}]}


async def test_a_model_accent_is_kept_whatever_the_area(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Решение тимлида 23.09: цвет, названный моделью, композитор больше не снимает,
    даже если по площади примеров шаблон ставит акцентом другой слот."""
    design = with_roles(manifest, accent_role(manifest, ColorRef.ACCENT3, 0.2))
    ir, composer, _ = await composed([KPI], manifest, content, variant_a, design)

    block = ir.block("k")
    assert isinstance(block, KpiBlock)
    assert block.items[0].color_ref is ColorRef.ACCENT1
    assert not [note for note in composer.notes if "акцентом не ставит" in note]


async def test_a_model_accent_of_the_template_is_kept(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    design = with_roles(manifest, accent_role(manifest, ColorRef.ACCENT1, 0.2))
    ir, composer, _ = await composed([KPI], manifest, content, variant_a, design)

    block = ir.block("k")
    assert isinstance(block, KpiBlock)
    assert block.items[0].color_ref is ColorRef.ACCENT1
    assert not [note for note in composer.notes if "акцентом не ставит" in note]


@pytest.mark.cold
async def test_a_cold_template_keeps_the_model_colors(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Правило 10: примеров нет — цвет модели остаётся, заметок о ролях цвета нет."""
    ir, composer, _ = await composed([KPI], manifest, content, variant_a)
    await composed([KPI], manifest, content, variant_a, composer=composer)

    block = ir.block("k")
    assert isinstance(block, KpiBlock) and block.items[0].color_ref is ColorRef.ACCENT1
    assert not [note for note in composer.notes if "роли цветов" in note]


# --- композиция: стиль списка ----------------------------------------------------


def bullets(style: str | None = None, *, texts: tuple[str, ...] = ITEMS,
            icons: tuple[str | None, ...] = (None, None, None),
            placeholder: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "block_id": "b", "type": "bullets",
        "items": [{"text": text, **({"icon": icon} if icon else {})}
                  for text, icon in zip(texts, icons, strict=True)],
    }
    if style:
        out["style"] = style
    if placeholder is not None:
        out["placeholder_idx"] = placeholder
    return out


async def list_of(
    block: dict[str, Any], manifest: TemplateManifest, content: ContentPackage,
    variant: VariantProfile,
) -> tuple[BulletsBlock, list[str]]:
    ir, composer, _ = await composed([block], manifest, content, variant)
    out = ir.block("b")
    assert isinstance(out, BulletsBlock)
    return out, composer.notes


async def test_numbers_written_into_the_items_make_a_numbered_list(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Нарушитель: «1. …, 2. …» в тексте — номер вышел бы дважды рядом с автонумерацией,
    а аудит чисел назвал бы «1» и «2» выдуманными."""
    texts = ("1. Разбор шаблона", "2. План колоды", "3) Вёрстка")
    block, notes = await list_of(bullets(texts=texts), manifest, content, variant_a)

    assert block.style is ListStyle.NUMBERED
    assert [item.text for item in block.items] == ["Разбор шаблона", "План колоды", "Вёрстка"]
    assert any("номера пунктов в тексте сняты — список нумерованный" in note for note in notes)


async def test_a_numbered_list_loses_the_numbers_in_its_text_even_alone(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Нарушитель из замера на VK Education: предел пунктов срезал список до одного,
    «1. Разбор…» осталось в тексте рядом с автонумерацией — «1. 1. Разбор…»."""
    block, notes = await list_of(
        bullets("numbered", texts=("1. Разбор шаблона",), icons=(None,)),
        manifest, content, variant_a,
    )
    assert block.style is ListStyle.NUMBERED
    assert [item.text for item in block.items] == ["Разбор шаблона"]
    assert any("номера пунктов в тексте сняты — нумерует список" in note for note in notes)


async def test_a_single_number_in_a_plain_list_is_text(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Норма: один пункт «1. …» без стиля — не нумерация; текст не трогается."""
    block, _ = await list_of(
        bullets(texts=("1. Разбор шаблона",), icons=(None,)), manifest, content, variant_a
    )
    assert block.style is None
    assert [item.text for item in block.items] == ["1. Разбор шаблона"]


async def test_numbers_out_of_order_are_text_not_numbering(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Норма: «37 %…», «5 млн…» — не нумерация; текст не трогается."""
    texts = ("37. Выручка", "5) Отток", "12. Клиенты")
    block, _ = await list_of(bullets(texts=texts), manifest, content, variant_a)
    assert block.style is None
    assert tuple(item.text for item in block.items) == texts


async def test_an_icon_list_without_an_icon_for_every_item_is_bulleted(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    block, notes = await list_of(
        bullets("icon", icons=("target", None, "shield")), manifest, content, variant_a
    )
    assert block.style is ListStyle.BULLETED
    assert all(item.icon is None for item in block.items)
    assert any("иконки нет у 1 пунктов из 3" in note for note in notes), notes


async def test_an_icon_list_in_a_placeholder_is_bulleted(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    block, notes = await list_of(
        bullets("icon", icons=ICONS, placeholder=1), manifest, content, variant_a
    )
    assert block.placeholder_idx == 1
    assert block.style is ListStyle.BULLETED
    assert any("в плейсхолдере 1 иконку к строке не привязать" in note for note in notes)


async def test_a_free_list_with_an_icon_for_every_item_is_an_icon_list(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    block, _ = await list_of(bullets(icons=ICONS), manifest, content, variant_a)
    assert block.style is ListStyle.ICON
    assert [item.icon for item in block.items] == list(ICONS)
    assert block.bbox is not None


async def test_a_well_formed_icon_list_is_left_alone(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Норма: свободный иконочный список с иконкой у каждого пункта — без заметок о стиле."""
    block, notes = await list_of(bullets("icon", icons=ICONS), manifest, content, variant_a)
    assert block.style is ListStyle.ICON
    assert not [note for note in notes if "буллеты b" in note or "иконочный список b" in note]


# --- композиция: промежуток и промпт ---------------------------------------------


async def test_free_blocks_are_spaced_by_the_design_system_step(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Промежуток между свободными блоками — шаг `grid.spacing` ДС, а не свой."""
    ds = derive(manifest)
    step = 3 * manifest.grid.gutter_emu
    ds = ds.model_copy(update={"grid": ds.grid.model_copy(update={
        "spacing": ds.grid.spacing.model_copy(update={"base_emu": step})
    })})
    ir, _, _ = await composed(
        [{"block_id": "q", "type": "quote", "text": "Шаблон задаёт язык колоды"},
         {"block_id": "c", "type": "callout", "tone": "risk", "text": "Срок под угрозой"}],
        manifest, content, variant_a, ds,
    )
    boxes = {block.block_id: block.bbox for block in ir.blocks if block.block_id in "qc"}
    assert None not in boxes.values()
    assert gap_between(boxes) == step  # type: ignore[arg-type]


async def test_the_prompt_gets_roles_and_kinds_not_coordinates(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    design = with_roles(manifest, accent_role(manifest, ColorRef.ACCENT3, 0.2))
    _, _, llm = await composed([], manifest, content, variant_a, design)

    prompt = llm.prompt
    assert "первый акцентный слот темы (`accent1`)" in prompt
    assert "Акценты этого шаблона по роли" not in prompt
    for style in ("bulleted", "numbered", "icon"):
        assert f"`{style}` —" in prompt
    assert "`quote`" in prompt and "tone: insight" in prompt and "tone: risk" in prompt
    emu = {str(v) for box in (manifest.content_bbox,) for v in (box.x, box.y, box.cx, box.cy)}
    assert not {word for word in re.findall(r"\d{5,}", prompt)} & emu, "в промпт ушли EMU"


@pytest.mark.cold
async def test_a_cold_prompt_names_accent1_as_on_any_template(
    manifest: TemplateManifest, content: ContentPackage, variant_a: VariantProfile
) -> None:
    """Акцент от ролей цвета больше не зависит: у шаблона без примеров промпт тот же."""
    _, _, llm = await composed([], manifest, content, variant_a)
    assert "первый акцентный слот темы (`accent1`)" in llm.prompt
    assert "Роли цветов" not in llm.prompt


def test_the_active_composer_prompt_is_the_design_system_one() -> None:
    """Проверяется не номер версии, а то, что активный промпт — по дизайн-системе.

    Номер был вписан числом (`1.3.1`) и ломался от любого поднятия версии, ничего при
    этом не проверяя по существу: 1.4.0 (`composer-response-schema-without-recipe`)
    тот же текст и несёт. Номер активной версии держит
    `test_composer_response_schema_without_recipe.py` — там он по делу.
    """
    bundle = get_prompt_registry().load("slide_composer")
    assert "Цитата и callout" in bundle.system_template
    assert "Стиль списка" in bundle.system_template


def test_the_composer_may_now_order_quote_callout_and_list_styles() -> None:
    """Обратное прежнему (DG4): рендер рисует цитату и callout — исключения больше нет,
    и схема ответа активной версии их содержит. Координат в ней по-прежнему нет."""
    assert WITHHELD_BLOCK_TYPES == {}
    schema = json.loads(
        (PROMPTS_DIR / "slide_composer" / "1.3.0" / "schema.json").read_text(encoding="utf-8")
    )
    kinds = set(schema["properties"]["blocks"]["items"]["discriminator"]["mapping"])
    assert {"quote", "callout", "bullets"} <= kinds
    assert "style" in schema["$defs"]["BulletsBlock"]["properties"]
    assert "icon" in schema["$defs"]["BulletItem"]["properties"]
    for name, definition in schema["$defs"].items():
        assert not {"x", "y", "cx", "cy"} & set(definition.get("properties", {})), name


# --- конвейер -------------------------------------------------------------------


@pytest.mark.cold
async def test_the_pipeline_composes_quote_and_a_numbered_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Правило 10 на всём конвейере: холодный шаблон python-pptx, модель заказывает
    цитату, callout и список с номерами в тексте — колода пишется, блоки на слайде,
    список нумерованный, номера из текста сняты."""
    import tests.integration.test_pipeline_end_to_end as e2e
    from tests.unit.test_ir_callout_and_quote import workspace

    def payload(self: Any) -> dict[str, Any]:
        return {"blocks": [
            {"block_id": "q", "type": "quote", "text": "Выручка выросла на 37,5 % за год",
             "author": "Отчёт"},
            {"block_id": "c", "type": "callout", "tone": "insight",
             "text": "Выручка выросла на 37,5 %"},
            {"block_id": "b", "type": "bullets", "items": [
                {"text": "1. Выручка выросла"}, {"text": "2. Клиентов больше"}]},
        ]}

    monkeypatch.setattr(e2e.FakeInference, "_slide", payload)
    result, _ = await e2e.run_pipeline(workspace(tmp_path))

    assert not result.interrupted
    assert result.exports["pptx"].is_file()
    for slide in result.state["deck"].slides:
        kinds = {block.block_id: block for block in slide.blocks}
        assert {"q", "c", "b"} <= set(kinds), slide.slide_id
        listing_block = kinds["b"]
        assert isinstance(listing_block, BulletsBlock)
        assert listing_block.style is ListStyle.NUMBERED
        assert not any(item.text[0].isdigit() for item in listing_block.items)


# --- аудит: текст цитаты и callout ---------------------------------------------


def grounded_content(*numbers: tuple[float, str | None]) -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="report", audience="правление", target_slides=6),
        facts=[
            Fact(fact_id=f"f{index:03d}", text="Выручка выросла",
                 numbers=[Number(value=value, unit=unit, raw=f"{value:g}")])
            for index, (value, unit) in enumerate(numbers, start=1)
        ],
    )


def audited_callout(text: str, manifest: TemplateManifest) -> list[Any]:
    area = manifest.content_bbox
    callout = CalloutBlock(block_id="c", text=text, tone=CalloutTone.INSIGHT,
                           x=area.x, y=area.y, cx=area.cx // 2, cy=area.cy // 2)
    colony = audit_deck(audit_slide(audit_title(), callout))
    context = context_for("content.numbers_grounded", colony, manifest,
                          content=grounded_content((37.0, "%")))
    return list(numbers_grounded(context))


def test_a_number_in_a_callout_not_in_the_materials_is_a_finding(
    manifest: TemplateManifest,
) -> None:
    """Нарушитель (решение тимлида 2): прежде аудит callout не читал вовсе, и выдуманное
    число в нём проходило молча."""
    findings = audited_callout("Выручка выросла на 42 % за квартал", manifest)
    assert [finding.block_id for finding in findings] == ["c"]
    assert findings[0].evidence["value"] == "42"


def test_a_number_in_a_callout_from_the_materials_is_not(manifest: TemplateManifest) -> None:
    assert audited_callout("Выручка выросла на 37 % за квартал", manifest) == []


def test_quote_and_callout_carry_text_for_the_audit() -> None:
    quote = QuoteBlock(block_id="q", text="Шаблон задаёт язык колоды", author="Бриф")
    callout = CalloutBlock(block_id="c", text="Срок под угрозой", tone=CalloutTone.RISK)
    assert carries_text(quote) and carries_text(callout)
    assert block_text(quote) == "Шаблон задаёт язык колоды"
    assert block_text(callout) == "Срок под угрозой"
