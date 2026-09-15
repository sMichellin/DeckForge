"""Разбор настоящих шаблонов. Changes (3) и (4).

Файлы шаблонов в репозиторий не кладутся: это чужие файлы, а репозиторий публичный.
Положите любые `.pptx` в `tests/fixtures/templates/` — тест подхватит их сам;
без них он пропускается, и CI это не ломает.

Проверяется не «совпало с эталоном», а что манифест **пригоден к употреблению**:
парсер обязан выдавать работоспособный результат на шаблоне, которого он не видел (C6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.enums import TextRole
from deckforge.domain.template import TemplateManifest
from deckforge.parsing import TemplateParser
from deckforge.parsing.layout_kind import UNCERTAIN_BELOW, needs_vlm

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"
TEMPLATES = sorted(FIXTURES.rglob("*.pptx")) + sorted(FIXTURES.rglob("*.potx"))

pytestmark = pytest.mark.skipif(
    not TEMPLATES, reason="нет шаблонов в tests/fixtures/templates/ (в git они не хранятся)"
)


@pytest.fixture(scope="module", params=[p.name for p in TEMPLATES])
def manifest(request: pytest.FixtureRequest) -> TemplateManifest:
    path = next(p for p in TEMPLATES if p.name == request.param)
    return TemplateParser().parse(path, use_cache=False)


def test_palette_is_complete(manifest: TemplateManifest) -> None:
    colors = manifest.theme.colors.model_dump()
    assert len(colors) == 12
    assert all(v.startswith("#") and len(v) == 7 for v in colors.values())


def test_fonts_are_extracted(manifest: TemplateManifest) -> None:
    assert manifest.theme.fonts.major_latin
    assert manifest.theme.fonts.minor_latin


def test_typography_scale_is_usable(manifest: TemplateManifest) -> None:
    ladder = manifest.size_ladder_pt
    assert len(ladder) >= 2, "шкала из одной ступени не даёт куда уменьшать текст"
    assert ladder == sorted(ladder, reverse=True)
    assert manifest.typography(TextRole.TITLE).size_pt >= manifest.typography(
        TextRole.BODY
    ).size_pt


def test_layouts_are_addressable(manifest: TemplateManifest) -> None:
    assert manifest.layouts
    ids = [layout.layout_id for layout in manifest.layouts]
    assert len(ids) == len(set(ids))
    for layout in manifest.layouts:
        assert layout.placeholders, "макет без плейсхолдеров в манифест попадать не должен"
        idxs = [ph.idx for ph in layout.placeholders]
        assert len(idxs) == len(set(idxs))


def test_placeholders_stay_inside_the_slide(manifest: TemplateManifest) -> None:
    slide = manifest.slide_size.bbox
    for layout in manifest.layouts:
        for ph in layout.placeholders:
            assert ph.bbox.x < slide.cx and ph.bbox.y < slide.cy, (
                f"{layout.layout_id}/{ph.idx} начинается за пределами слайда"
            )


def test_grid_is_present_however_it_was_obtained(manifest: TemplateManifest) -> None:
    assert manifest.grid.guides_source in {"xml", "inferred"}
    assert manifest.slide_size.bbox.contains(manifest.content_bbox)


def test_every_layout_is_either_confident_or_routed_to_vlm(manifest: TemplateManifest) -> None:
    """Эвристика обязана дать вид **каждому** макету и честно сказать, где она не уверена.

    Планка «≥ 80 % верных видов» из плана относится к change (5), где поверх эвристики
    включается VLM. Здесь проверяется то, что делает ту планку достижимой: ни один макет
    не остаётся без вида, и каждый спорный случай помечен для доклассификации.
    """
    for layout in manifest.layouts:
        assert layout.kind is not None
        assert 0.0 <= layout.kind_confidence <= 1.0
        assert needs_vlm(layout.kind_confidence) or layout.kind_confidence >= UNCERTAIN_BELOW


def test_heuristic_resolves_a_meaningful_share_on_its_own(manifest: TemplateManifest) -> None:
    """Регрессионный порог, а не цель: ниже него эвристика перестала бы экономить вызовы VLM.

    На шаблонах организаторов доля уверенных видов — от 43 % (VK Tech, много «своих»
    макетов под ручную вёрстку) до 100 % (VK WorkSpace). Поднимать её — работа change (5).
    """
    confident = [layout for layout in manifest.layouts if not needs_vlm(layout.kind_confidence)]
    assert len(confident) >= len(manifest.layouts) * 0.4


def test_manifest_round_trips_through_json(manifest: TemplateManifest) -> None:
    """Манифест кэшируется как JSON — значит, обязан читаться обратно без потерь."""
    assert TemplateManifest.model_validate_json(manifest.model_dump_json()) == manifest
