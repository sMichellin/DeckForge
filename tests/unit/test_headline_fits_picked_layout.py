"""Заголовок под полосу выбранного макета. Change `headline-fits-picked-layout` (A11).

После #111 предел заголовка планировщику называется по медиане полос шаблона (VK Tech —
63 знака), а выбранные макеты держат 24–32: композиция подрезала 7 заголовков из 9.
Второй заход `HeadlineRewriter` после `pick_layout` меряет каждый заголовок полосой
его макета, тем же `fit_block`, и стоит один вызов на колоду.

Модель подделана: проверяется не качество формулировок, а то, что мерило то же,
что у подрезки, что в модель уходят только не вставшие и что вызов один.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from deckforge.composition.composer import SlideComposer
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent, TextRole
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import LayoutSpec, PlaceholderSpec, TemplateManifest
from deckforge.inference.client import Completion
from deckforge.pipeline.nodes import compose as compose_module
from deckforge.pipeline.nodes.plan import _HEADLINE_SAMPLE, layout_headline_band
from deckforge.pipeline.state import DeckState
from deckforge.planning.headlines import Band, HeadlineRewriter
from deckforge.registry import load_variant_profiles
from tests.unit.test_pipeline_graph import deps, runtime

CM = 360_000

#: 60 знаков: столько планировщик пишет при пределе 63 по медиане полос VK Tech.
LONG = "Выручка выросла на треть за счёт корпоративных клиентов и рынков"
#: 24 знака: вывод, который помещается в предел переписчика в тестах захода.
SHORT = "Выручка выросла на треть"


class FakeLlm:
    """Отдаёт заготовленный JSON, считает вызовы и помнит, что ему прислали."""

    model = "fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        self.prompts.append("\n".join(str(m.get("content", "")) for m in messages))
        return Completion(text=json.dumps(self.payload, ensure_ascii=False), model=self.model)


def variants(**by_slide: list[str]) -> dict[str, Any]:
    """Ответ скилла `headline_writer@1.2.0`: варианты по слайдам."""
    return {"headlines": [{"slide_id": sid, "variants": v} for sid, v in by_slide.items()]}


def title_band(cx_cm: float, cy_cm: float) -> PlaceholderSpec:
    return PlaceholderSpec(
        idx=0, ph_type="TITLE", role=TextRole.TITLE,
        x=CM // 2, y=CM, cx=round(cx_cm * CM), cy=round(cy_cm * CM),
    )


def with_title(layout: LayoutSpec, band: PlaceholderSpec | None) -> LayoutSpec:
    rest = [ph for ph in layout.placeholders if ph.role is not TextRole.TITLE]
    return layout.model_copy(update={"placeholders": [*(([band]) if band else []), *rest]})


def _with_content_band(manifest: TemplateManifest, cx_cm: float) -> TemplateManifest:
    layouts = [
        with_title(layout, title_band(cx_cm, 2.1)) if layout.capacity.max_chars_body else layout
        for layout in manifest.layouts
    ]
    return manifest.model_copy(update={"layouts": layouts})


def narrow_content(manifest: TemplateManifest) -> TemplateManifest:
    """Шаблон, где у макета содержания полоса заголовка узкая, как у VK Tech (высота 2,1 см):
    вывод в три-пять слов держит, 60-знаковый заголовок — нет. У титула полоса просторная.

    Ширина подбирается мерой, а не задаётся числом: синтетической гарнитуры нет ни на одной
    машине, и заменитель у Windows и у образа CI разный — 14 см держат 27 знаков на одной
    и 18 на другой. Берётся самая узкая полоса, которая ещё считается полосой для вывода.
    """
    for tenths in range(60, 400, 5):
        tight = _with_content_band(manifest, tenths / 10)
        if layout_headline_band(content_layout(tight), tight) is not None:
            return tight
    raise AssertionError("ни одна ширина полосы не удержала три слова")


def content_layout(manifest: TemplateManifest) -> LayoutSpec:
    return next(layout for layout in manifest.layouts if layout.capacity.max_chars_body)


def fitting(manifest: TemplateManifest) -> str:
    """Самое длинное начало образца, которое держит полоса макета содержания."""
    band = layout_headline_band(content_layout(manifest), manifest)
    assert band is not None
    words = _HEADLINE_SAMPLE.split()
    return next(
        text
        for n in range(len(words), 0, -1)
        if len(text := " ".join(words[:n])) == band.limit
    )


@pytest.fixture
def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[Fact(fact_id="f001", text="Выручка выросла на треть за год")],
    )


def plan_of(*headlines: str) -> DeckPlan:
    return DeckPlan(
        deck_id="d1",
        variant="A",
        seed=1,
        slides=[
            SlidePlan(
                slide_id=f"s{i:02d}", intent=SlideIntent.PROBLEM, headline=text,
                fact_refs=["f001"],
            )
            for i, text in enumerate(headlines, start=1)
        ],
    )


def shorter_than(limit: int) -> Band:
    return Band(fits=lambda text: len(text) <= limit, limit=limit)


# --- мерило полосы -------------------------------------------------------------


def test_band_measures_exactly_what_the_composer_trims(manifest: TemplateManifest) -> None:
    """Мерило захода и мерило подрезки — один и тот же вопрос к `fit_block`.

    Разойдись они — заход объявил бы заголовок уместившимся, а композиция всё равно
    отрезала бы от него слова. Поэтому сверка идёт с самой подрезкой композитора.
    """
    tight = narrow_content(manifest)
    layout = content_layout(tight)
    band = layout_headline_band(layout, tight)
    assert band is not None

    composer = SlideComposer(FakeLlm({}))
    words = LONG.split()
    for n in range(1, len(words) + 1):
        text = " ".join(words[:n])
        block = TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text=text)
        untouched = composer._trim_headline(block, layout, tight, "s01").text == text
        assert band.fits(text) is untouched, f"мерила разошлись на «{text}»"

    assert band.fits(fitting(tight)) and not band.fits(LONG)


def test_band_limit_is_the_band_of_this_layout(manifest: TemplateManifest) -> None:
    """Предел — мера полосы этого макета, а не медиана шаблона: следующее слово не влезает."""
    tight = narrow_content(manifest)
    band = layout_headline_band(content_layout(tight), tight)
    assert band is not None

    kept = fitting(tight)
    after = _HEADLINE_SAMPLE.split()[len(kept.split())]
    assert band.fits(kept)
    assert not band.fits(f"{kept} {after}")
    assert band.limit < len(LONG), "предел не мера полосы: длинный заголовок его не нарушает"


def test_cover_band_of_one_word_is_not_a_band_for_a_conclusion(
    manifest: TemplateManifest,
) -> None:
    """Полосу ради одного крупного слова заводят обложки: вывод в неё не просят."""
    tiny = content_layout(manifest)
    tiny = with_title(tiny, title_band(3.0, 1.2))
    assert layout_headline_band(tiny, manifest) is None


def test_layout_without_a_title_band_is_not_measured(manifest: TemplateManifest) -> None:
    """Нет полосы — нечего мерить: подрезки композиции там тоже нет."""
    bare = with_title(content_layout(manifest), None)
    assert layout_headline_band(bare, manifest) is None


def test_roomy_band_needs_no_rewrite(manifest: TemplateManifest) -> None:
    """Норма: просторная полоса держит заголовок, который план и написал."""
    band = layout_headline_band(content_layout(manifest), manifest)
    assert band is not None and band.fits(LONG)


# --- заход переписчика -----------------------------------------------------------


def test_only_headlines_over_their_own_band_go_to_the_model(content: ContentPackage) -> None:
    """В пачке — только не вставшие, и у каждого свой предел в промпте."""
    llm = FakeLlm(variants(s01=[SHORT]))
    rewriter = HeadlineRewriter(llm)
    plan = plan_of(LONG, SHORT, LONG)
    bands = {"s01": shorter_than(24), "s02": shorter_than(24), "s03": shorter_than(70)}

    out = asyncio.run(rewriter.rewrite_for_layouts(plan, content, bands=bands, seed=1))

    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    assert "## s01 (предел 24 знаков)" in prompt
    assert "## s02" not in prompt, "заголовок, который влез, ушёл модели"
    assert "## s03" not in prompt, "полоса s03 держит его, а мерило взято чужое"
    assert [s.headline for s in out.slides] == [SHORT, SHORT, LONG]
    assert any("s01: заголовок переписан под рамку" in note for note in rewriter.notes)


def test_one_call_per_deck_even_when_nothing_fits(content: ContentPackage) -> None:
    """Бюджет — один вызов: не вставший и теперь заголовок подрежет композиция."""
    almost = "Выручка выросла на треть за счёт клиентов"
    llm = FakeLlm(variants(s01=[almost]))
    rewriter = HeadlineRewriter(llm)

    out = asyncio.run(
        rewriter.rewrite_for_layouts(
            plan_of(LONG), content, bands={"s01": shorter_than(24)}, seed=1
        )
    )

    assert len(llm.prompts) == 1, "второго захода с промахом здесь быть не должно"
    assert out.slides[0].headline == almost, "короче — значит меньше выбросит подрезка"
    assert any("остаток подрежет композиция" in note for note in rewriter.notes)


def test_slide_without_a_band_and_fitting_deck_cost_nothing(content: ContentPackage) -> None:
    """Норма: мерить нечем или всё влезло — модель не зовут вовсе."""
    llm = FakeLlm(variants(s01=["Что-то другое"]))
    rewriter = HeadlineRewriter(llm)
    plan = plan_of(LONG, SHORT)

    out = asyncio.run(
        rewriter.rewrite_for_layouts(plan, content, bands={"s02": shorter_than(24)}, seed=1)
    )

    assert llm.prompts == []
    assert out == plan
    assert rewriter.notes == []


# --- узел compose ---------------------------------------------------------------


class RecordingComposer:
    """Композитор, который помнит, с каким заголовком к нему пришёл слайд."""

    seen: ClassVar[dict[str, str]] = {}

    def __init__(self, *_: Any, **__: Any) -> None:
        self.notes: list[str] = []

    async def compose(self, slide: SlidePlan, *_: Any, **__: Any) -> SlideIR:
        RecordingComposer.seen[slide.slide_id] = slide.headline
        return SlideIR(
            slide_id=slide.slide_id,
            layout_id="L07",
            variant="A",
            blocks=[
                TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                          text=slide.headline)
            ],
        )


async def test_compose_node_rewrites_to_the_band_of_the_picked_layout(
    manifest: TemplateManifest,
    content: ContentPackage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Нарушитель: заголовок по медиане шаблона длиннее полосы макета, выбранного слайду.

    До композиции он уходит модели и приходит к композитору уже вставшим — подрезать
    нечего. Норма рядом: короткий заголовок модели не шлют. Исход — в отчёте прогона,
    переписанный заголовок — в плане состояния.
    """
    tight = narrow_content(manifest)
    short = fitting(tight)
    fast = FakeLlm(variants(s01=[LONG, short]))
    RecordingComposer.seen = {}
    monkeypatch.setattr(compose_module, "SlideComposer", RecordingComposer)

    state: DeckState = {
        "content": content,
        "manifest": tight,
        "variant": load_variant_profiles()["A"],
        "seed": 1,
        "plan": plan_of(LONG, short),
    }
    out = await compose_module.compose_node(
        state, runtime(deps(tmp_path, llm=object(), llm_fast=fast))
    )

    assert len(fast.prompts) == 1, "один вызов на колоду"
    assert "## s02" not in fast.prompts[0]
    assert RecordingComposer.seen == {"s01": short, "s02": short}
    assert [s.headline for s in out["plan"].slides] == [short, short]
    assert any(
        note.startswith("заголовок под макет: слайд s01: заголовок переписан под рамку")
        for note in out["notes"]
    )


# --- холодный шаблон (правило 10) -------------------------------------------------


def test_bands_on_a_template_nobody_tuned_for(tmp_path: Path) -> None:
    """Стандартный шаблон python-pptx: полоса мерится у каждого макета, мерило совпадает
    с подрезкой композитора, заголовок в пять слов предел не нарушает."""
    from deckforge.parsing import TemplateParser
    from tests.integration.test_native_objects import build_template

    manifest = TemplateParser(cache_dir=tmp_path / "cache").parse(
        build_template(tmp_path / "template.pptx")
    )
    composer = SlideComposer(FakeLlm({}))
    measured = 0
    for layout in manifest.layouts:
        band = layout_headline_band(layout, manifest)
        if band is None:
            continue
        measured += 1
        idx = next(ph.idx for ph in layout.placeholders if ph.role is TextRole.TITLE)
        for text in (SHORT, LONG):
            block = TextBlock(block_id="t", placeholder_idx=idx, role=TextRole.TITLE, text=text)
            untouched = composer._trim_headline(block, layout, manifest, "s01").text == text
            assert band.fits(text) is untouched, f"{layout.layout_id}: мерила разошлись"
        assert 0 < band.limit <= 70

    assert measured > 0, "ни у одного макета стандартного шаблона полоса не измерилась"
