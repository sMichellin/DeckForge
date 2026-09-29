"""Текст, оборванный посреди слова, — находка. Change `the-cut-word-is-found`, план Б, круг 2,
корень К1 (`docs/agents/tasks-plan-b-round-2.md`), поток C, #245.

Первый живой прогон `by_example` 29.09: семь текстов на трёх колодах оборваны посреди слова,
а строки мерила 1–7 зелёные. Признака два: текст длиной ровно предел текстового места
(оборвала грамматика) и последнее слово — обрывок слова материалов (сократила модель).

Сценарии — из дельты `openspec/changes/the-cut-word-is-found/specs/audit-deterministic/`.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from deckforge.audit.semantic.grounding import cut_word, word_cut
from deckforge.designsystem import derive
from deckforge.designsystem.models import (
    ExamplePassport,
    Place,
    PlaceGroup,
    PlaceKind,
    Recipe,
    RecipeKind,
    TypeLevel,
    Zone,
)
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, SlideIR, TextBlock
from deckforge.domain.template import TemplateExample, TemplateManifest
from deckforge.pipeline.replay import from_fixture, reaudit
from tests.unit._audit_builders import context_for, deck

CHECK = "content.word_cut"
RUNS = Path(__file__).resolve().parents[1] / "fixtures" / "runs"
SOURCE = {
    "паттерн", "подбирается", "под", "новый", "контент", "процессов", "труда",
    "минут", "фирменный", "стиль", "самостоятельно",
}


# --- признак «оборванное слово» -----------------------------------------------------------


@pytest.mark.parametrize(("text", "cut"), [
    ("Подобранный пат.", "пат"),
    ("Сокращение времени с часов до мин", "мин"),
])
def test_a_word_the_model_shortened_is_cut(text: str, cut: str) -> None:
    """Нарушитель: модель сократила слово материалов, чтобы уложиться в место."""
    assert cut_word(text, SOURCE) == cut


@pytest.mark.parametrize("text", [
    "Массовый процесс",           # «процессов» в материалах — форма слова, а не обрыв
    "Ручной труд",                # «труда» — окончание в одну букву
    "ИИ делает слайды сам",       # служебное слово при «самостоятельно»
    "Паттерн под новый контент",  # целое слово материалов
    "Итог за квартал",            # слова материалов с него не начинаются
])
def test_a_whole_word_is_not_cut(text: str) -> None:
    """Норма: падежная форма, служебное слово, целое слово — не обрывок."""
    assert cut_word(text, SOURCE) is None


def test_without_sources_the_word_is_not_judged() -> None:
    assert cut_word("Подобранный пат.", set()) is None


# --- признак «предел места»: проверка целиком ---------------------------------------------


def _recipe() -> Recipe:
    zones = [
        Zone(zone_id="zt", xml_id=900, role=TypeLevel.SLIDE_TITLE, capacity_chars=40),
        Zone(zone_id="za", xml_id=901, role=TypeLevel.BODY, capacity_chars=40),
        Zone(zone_id="zn", xml_id=902, role=TypeLevel.BODY, capacity_chars=10),
    ]
    places = [
        Place(place_id="p01", kind=PlaceKind.TEXT, zone_id="zt", xml_id=900,
              role=TypeLevel.SLIDE_TITLE, capacity_chars=30),
        Place(place_id="p02", kind=PlaceKind.TEXT, zone_id="za", xml_id=901,
              role=TypeLevel.BODY, capacity_chars=23),
        Place(place_id="p03", kind=PlaceKind.NUMBER, zone_id="zn", xml_id=902,
              role=TypeLevel.BODY, capacity_chars=3),
    ]
    passport = ExamplePassport(groups=[
        PlaceGroup(group_id=f"g{n:02d}", places=[place]) for n, place in enumerate(places, 1)
    ])
    return Recipe(recipe_id="ex005", example_index=1, kind=RecipeKind.TEXT, zones=zones,
                  passport=passport)


def run(manifest: TemplateManifest, body: str, number: str = "37%") -> list:
    slide = SlideIR(slide_id="s03", layout_id="L07", variant="A", recipe_id="ex005", blocks=[
        TextBlock(block_id="b0", role=TextRole.TITLE, text="Шаблон держит стиль", zone_id="zt"),
        TextBlock(block_id="b1", role=TextRole.BODY, text=body, zone_id="za"),
        TextBlock(block_id="b2", role=TextRole.BODY, text=number, zone_id="zn"),
    ])
    with_examples = manifest.model_copy(update={"examples": [TemplateExample(slide_index=1)]})
    design = derive(with_examples).model_copy(update={"recipes": [_recipe()]})
    content = ContentPackage(
        brief=Brief(purpose="report", audience="правление", target_slides=10),
        facts=[Fact(fact_id="f001", text="AI не копирует фирменный стиль шаблона"),
               Fact(fact_id="f002", text="Сервис с открытым кодом собирает сотни слайдов")],
    )
    ctx = context_for(CHECK, deck(slide), with_examples, content=content)
    return list(word_cut(replace(ctx, design_system=design)))


def test_a_text_at_the_limit_of_its_place_is_cut(manifest: TemplateManifest) -> None:
    """Нарушитель: 23 знака в месте на 23, «фирменны» в материалах нет — оборвано на знаке."""
    findings = run(manifest, "AI не копирует фирменны")

    assert [(f.block_id, f.evidence["sign"]) for f in findings] == [("b1", "limit")]


def test_a_text_below_the_limit_is_not_cut(manifest: TemplateManifest) -> None:
    """Норма: текст короче предела и кончается целым словом."""
    assert run(manifest, "AI держит стиль") == []


def test_a_number_at_the_limit_of_its_place_is_whole(manifest: TemplateManifest) -> None:
    """Норма: «10x» ровно в три знака места-числа — законно, по пределу не судится."""
    assert run(manifest, "AI держит стиль", number="10x") == []


def test_a_bullet_item_is_judged_too(manifest: TemplateManifest) -> None:
    """Пункт списка вне места: обрывок слова материалов — находка."""
    slide = SlideIR(slide_id="s04", layout_id="L07", variant="A", blocks=[
        BulletsBlock(block_id="b1", items=[BulletItem(text="Держит фирменный стиль"),
                                           BulletItem(text="Не копирует фирмен")]),
    ])
    content = ContentPackage(
        brief=Brief(purpose="report", audience="правление", target_slides=10),
        facts=[Fact(fact_id="f001", text="AI не копирует фирменный стиль шаблона")],
    )
    findings = list(word_cut(context_for(CHECK, deck(slide), manifest, content=content)))

    assert [(f.block_id, f.evidence["sign"]) for f in findings] == [("b1", "word")]


# --- мерило: фикстуры прогонов ------------------------------------------------------------


def _found(day: str) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for name in ("workspace", "vk-tech", "education"):
        folder = RUNS / day / name
        if not folder.is_dir():
            pytest.skip(f"нет фикстуры {day}/{name}")
        report = asyncio.run(reaudit(from_fixture(folder))).report
        out |= {(name, f.slide_id or "", f.evidence["text"]) for f in report.findings
                if f.check_id == CHECK}
    return out


def test_a_whole_word_at_the_limit_is_not_cut(manifest: TemplateManifest) -> None:
    """Норма (ревью тимлида, WorkSpace `c950b5936b7a` s10): «Open-source для слайдов» ровно
    в 23 знака, «слайдов» в материалах целиком. После #269 схема даёт полторы ёмкости —
    текст ровно в ёмкость законен, длина сама по себе обрыва не доказывает."""
    assert len("Open-source для слайдов") == 23
    assert run(manifest, "Open-source для слайдов") == []


def test_the_by_example_runs_of_29_09_have_six_cut_words() -> None:
    """Мерило К1, строка 6б: шесть слов, оборванных посреди. «Паттерн под новый» (VK Tech s07)
    не находка: ровно в предел, но «новый» — целое слово материалов; оборвана фраза,
    а не слово (ревью тимлида)."""
    expected = {
        ("workspace", "s03"): "копирует фирменны",
        ("workspace", "s04"): "с часов до мин",
        ("workspace", "s10"): "для презент",
        ("vk-tech", "s01"): "создание слай",
        ("education", "s06"): "слайды сократ.",
    }
    found = _found("2026-09-29")

    assert len(found) == 6
    for (name, slide), tail in expected.items():
        assert any(n == name and s == slide and t.endswith(tail) for n, s, t in found), tail
    vk_s07 = sorted(t for n, s, t in found if (n, s) == ("vk-tech", "s07"))
    assert vk_s07 == ["Подобранный пат."]


def test_the_legacy_runs_of_28_09_have_none() -> None:
    """Норма: на прежнем пути текст не упирался в грамматику — находок нет."""
    assert _found("2026-09-28") == set()
