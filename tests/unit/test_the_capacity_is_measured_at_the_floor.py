"""Ёмкость места мерится кеглем, которым оно будет написано.

Change `the-capacity-is-measured-at-the-floor` (план Б, стык со строкой приёмки 7,
issue #243). Сценарии — из дельты этого change.

Манифест берётся из фикстуры прогона 28.09: в нём настоящая шкала кеглей шаблона,
и тест идёт в CI, где файлов шаблонов нет.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.composition.passport import fit_measure, probe_size, sample, with_passports
from deckforge.designsystem.models import TypeLevel, Zone
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.replay import from_fixture

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28"


@pytest.fixture(scope="module")
def vk_tech():
    return from_fixture(FIXTURES / "vk-tech")


def zone(size_pt: float | None) -> Zone:
    return Zone(zone_id="z01", role=TypeLevel.CAPTION, capacity_chars=30, size_pt=size_pt)


def test_a_size_below_the_floor_is_measured_at_the_floor(vk_tech) -> None:
    """Нарушитель: автор набрал подпись мельче порога.

    У VK Tech `ex018` карточки подписаны 9 pt при пороге 10 pt — 317 мест из 650
    на этом шаблоне. Вёрстка такой текст поднимет до порога, и место вместит меньше,
    чем обещал паспорт.
    """
    floor = DesignRules(vk_tech.manifest, vk_tech.design_system).reading_floor_pt

    size = probe_size(zone(9.0), vk_tech.manifest, floor)

    assert size is not None
    assert size >= floor
    assert size in vk_tech.manifest.size_ladder_pt, "кегль — только из шкалы шаблона"


def test_a_size_at_or_above_the_floor_keeps_the_authors_size(vk_tech) -> None:
    """Норма: кегль автора не ниже порога — меряем им, как раньше."""
    floor = DesignRules(vk_tech.manifest, vk_tech.design_system).reading_floor_pt

    assert probe_size(zone(floor), vk_tech.manifest, floor) is None
    assert probe_size(zone(floor + 2), vk_tech.manifest, floor) is None


def test_a_zone_without_a_size_keeps_the_old_path(vk_tech) -> None:
    """Норма: кегля у зоны нет — мерить нечем, правило молчит."""
    floor = DesignRules(vk_tech.manifest, vk_tech.design_system).reading_floor_pt

    assert probe_size(zone(None), vk_tech.manifest, floor) is None


def test_the_promised_capacity_holds_at_the_raised_size(vk_tech) -> None:
    """Мерило change: обещанное число знаков встаёт в место поднятым кеглем.

    Прежде паспорт мерил кеглем автора, и на VK Tech обещал 10 661 знак в местах,
    которые вёрстка напишет крупнее. Проверяется на самом шаблоне прогона: берём место
    с кеглем ниже порога и заливаем в него ровно обещанное.
    """
    fonts = FontLibrary.default()
    ds, _report = with_passports(vk_tech.design_system, vk_tech.manifest, fonts)
    rules = DesignRules(vk_tech.manifest, ds)
    floor = rules.reading_floor_pt

    checked = 0
    for recipe in ds.recipes:
        if recipe.passport is None:
            continue
        zones = {item.zone_id: item for item in recipe.zones}
        for place in recipe.passport.places:
            source = zones.get(place.zone_id or "")
            if source is None or source.size_pt is None or source.size_pt >= floor:
                continue
            if not place.capacity_chars:
                continue
            fits = fit_measure(vk_tech.manifest, ds, fonts)
            probe = sample(place.capacity_chars)
            assert fits(recipe, {source.zone_id: probe})[source.zone_id], (
                f"{recipe.recipe_id}/{place.place_id}: обещано "
                f"{place.capacity_chars} знаков, а они не встают"
            )
            checked += 1
            if checked == 3:
                return
    assert checked, "на этом шаблоне нет мест с кеглем ниже порога — проверять нечего"


def test_the_slide_is_measured_by_the_same_code(vk_tech) -> None:
    """Норма: паспорт и вписывание меряют одним кодом — иначе обещание разойдётся с делом."""
    fonts = FontLibrary.default()
    ds, _report = with_passports(vk_tech.design_system, vk_tech.manifest, fonts)
    recipe = next(item for item in ds.recipes if item.passport is not None)
    place = next(item for item in recipe.passport.places if item.capacity_chars)
    zone_id = place.zone_id or ""

    slide = SlideIR(
        slide_id="s01",
        layout_id=vk_tech.manifest.layouts[0].layout_id,
        variant="A",
        recipe_id=recipe.recipe_id,
        blocks=[TextBlock(block_id="b1", role="body", text=sample(place.capacity_chars),
                          zone_id=zone_id)],
    )

    report = fit_slide(slide, vk_tech.manifest, fonts=fonts,
                       design=DesignRules(vk_tech.manifest, ds)).fit_report

    assert "b1" in report, "блок в зоне обязан попасть в отчёт вписывания"
