"""Полный разбор пакета шаблона. Changes (3) `template-parsing-core` и (4) `theme-extraction`."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.enums import ColorRef, LayoutKind, TextRole
from deckforge.parsing import PARSER_VERSION, TemplateParser, template_id_of
from deckforge.parsing.package import NotATemplateError
from deckforge.parsing.template import aspect_of
from tests.integration.synthetic_template import SLIDE_CX, build


@pytest.fixture
def template(tmp_path: Path) -> Path:
    return build(tmp_path / "synthetic.pptx")


@pytest.fixture
def parser(tmp_path: Path) -> TemplateParser:
    return TemplateParser(cache_dir=tmp_path / "cache")


def test_manifest_is_built_end_to_end(template: Path, parser: TemplateParser) -> None:
    manifest = parser.parse(template)

    assert manifest.slide_size.cx_emu == SLIDE_CX
    assert manifest.slide_size.aspect == "16:9"
    assert manifest.theme.colors.accent1 == "#2E6BE6"
    assert manifest.theme.fonts.major_latin == "TestSans Display"
    assert manifest.parser_version == PARSER_VERSION
    assert manifest.source_name == "synthetic.pptx"


def test_template_id_is_the_file_hash(template: Path, parser: TemplateParser) -> None:
    assert parser.parse(template).template_id == template_id_of(template)
    assert template_id_of(template).startswith("sha256:")


def test_all_layouts_are_present_and_classified(template: Path, parser: TemplateParser) -> None:
    manifest = parser.parse(template)
    kinds = {layout.name: layout.kind for layout in manifest.layouts}

    assert len(manifest.layouts) == 3
    assert kinds["Титул"] is LayoutKind.TITLE
    assert kinds["Заголовок и содержимое"] is LayoutKind.BULLETS
    assert kinds["Две колонки"] is LayoutKind.TWO_COLUMN
    assert all(layout.kind_source == "heuristic" for layout in manifest.layouts)


def test_layout_ids_are_unique_and_addressable(template: Path, parser: TemplateParser) -> None:
    manifest = parser.parse(template)
    ids = [layout.layout_id for layout in manifest.layouts]
    assert len(ids) == len(set(ids))
    assert all(manifest.layout(layout_id) is not None for layout_id in ids)


def test_typography_scale_is_derived_from_the_template(
    template: Path, parser: TemplateParser
) -> None:
    manifest = parser.parse(template)
    sizes = {step.role: step.size_pt for step in manifest.typography_scale}

    assert sizes[TextRole.TITLE] == 40
    assert sizes[TextRole.BODY] == 18
    assert manifest.size_ladder_pt == sorted(manifest.size_ladder_pt, reverse=True)
    assert manifest.typography(TextRole.TITLE).bold is True


def test_colours_in_the_scale_are_theme_references(template: Path, parser: TemplateParser) -> None:
    """ADR-002: в манифесте живут ссылки на тему, а не коды цветов."""
    manifest = parser.parse(template)
    assert all(isinstance(step.color_ref, ColorRef) for step in manifest.typography_scale)


def test_capacity_is_computed_per_layout(template: Path, parser: TemplateParser) -> None:
    manifest = parser.parse(template)
    bullets = next(layout for layout in manifest.layouts if layout.kind is LayoutKind.BULLETS)
    title = next(layout for layout in manifest.layouts if layout.kind is LayoutKind.TITLE)

    assert bullets.capacity.max_bullets > 0
    assert bullets.capacity.max_chars_body > title.capacity.max_chars_body


def test_placeholders_inherit_geometry_from_the_master(tmp_path: Path) -> None:
    """Макет, не задавший геометрию, берёт её у мастера — и наоборот, пустой мастер не мешает."""
    inherited = TemplateParser().parse(build(tmp_path / "a.pptx"), use_cache=False)
    standalone = TemplateParser().parse(
        build(tmp_path / "b.pptx", empty_master=True), use_cache=False
    )
    assert len(inherited.layouts) == len(standalone.layouts) == 3


def test_grid_is_inferred_when_the_template_has_no_guides(
    template: Path, parser: TemplateParser
) -> None:
    manifest = parser.parse(template)
    assert manifest.grid.guides_source == "inferred"
    assert manifest.grid.margins_emu.left > 0
    assert manifest.grid.guides_x_emu, "направляющие обязаны выводиться, а не оставаться пустыми"


def test_explicit_guides_are_preferred(tmp_path: Path) -> None:
    manifest = TemplateParser().parse(
        build(tmp_path / "guided.pptx", with_view_props=True), use_cache=False
    )
    assert manifest.grid.guides_source == "xml"


def test_content_box_fits_inside_the_slide(template: Path, parser: TemplateParser) -> None:
    manifest = parser.parse(template)
    assert manifest.slide_size.bbox.contains(manifest.content_bbox)


def test_chart_series_colours_come_from_the_theme(template: Path, parser: TemplateParser) -> None:
    manifest = parser.parse(template)
    assert manifest.chart_defaults.series_color_refs[0] is ColorRef.ACCENT1
    assert len(manifest.chart_defaults.series_color_refs) == 6


def test_footer_is_detected(template: Path, parser: TemplateParser) -> None:
    assert parser.parse(template).decor.footer.present is True


# --- кэш ---------------------------------------------------------------------


def test_second_parse_comes_from_cache(
    template: Path, parser: TemplateParser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Повторный прогон того же шаблона не должен разбирать пакет заново (бюджет §12)."""
    first = parser.parse(template)
    cache_file = parser._cache_path(first.template_id)
    assert cache_file is not None and cache_file.exists()

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("пакет разбирается повторно, хотя есть кэш")

    monkeypatch.setattr(TemplateParser, "_build", explode)
    assert parser.parse(template) == first


def test_cache_is_invalidated_by_parser_version(template: Path, parser: TemplateParser) -> None:
    """Манифест, снятый прежней версией парсера, кэшем не считается."""
    manifest = parser.parse(template)
    path = parser._cache_path(manifest.template_id)
    assert path is not None
    path.write_text(
        manifest.model_dump_json().replace(f'"{PARSER_VERSION}"', '"0.0.1"'), encoding="utf-8"
    )
    assert parser.load_cached(manifest.template_id) is None


def test_parsing_without_cache_dir_works(template: Path) -> None:
    assert TemplateParser().parse(template).layouts


# --- устойчивость ------------------------------------------------------------


def test_broken_file_fails_with_a_readable_error(tmp_path: Path) -> None:
    """Пользователь загрузил не то — он должен это понять, а не увидеть BadZipFile."""
    broken = tmp_path / "broken.pptx"
    broken.write_bytes(b"PK\x03\x04 not a presentation")
    with pytest.raises(NotATemplateError, match="не открывается"):
        TemplateParser().parse(broken, use_cache=False)


def test_zip_without_presentation_part_is_rejected(tmp_path: Path) -> None:
    import zipfile as zf

    not_a_deck = tmp_path / "archive.pptx"
    with zf.ZipFile(not_a_deck, "w") as z:
        z.writestr("readme.txt", "просто архив")
    with pytest.raises(NotATemplateError, match=r"presentation\.xml"):
        TemplateParser().parse(not_a_deck, use_cache=False)


@pytest.mark.parametrize(
    ("cx", "cy", "expected"),
    [
        (12_192_000, 6_858_000, "16:9"),
        (9_144_000, 5_143_500, "16:9"),
        (9_144_000, 6_858_000, "4:3"),
        (0, 0, "unknown"),
    ],
)
def test_aspect_is_computed(cx: int, cy: int, expected: str) -> None:
    assert aspect_of(cx, cy) == expected


# --- классификация макетов, change (5) ---------------------------------------


def test_parser_classifies_every_layout(template: Path, parser: TemplateParser) -> None:
    """Ни один макет не остаётся с техническим `pending` после сборки манифеста."""
    manifest = parser.parse(template)
    for layout in manifest.layouts:
        assert layout.kind_source in {"heuristic", "vlm", "vlm+heuristic"}
        assert 0.0 < layout.kind_confidence <= 1.0


def test_parser_uses_the_injected_classifier(tmp_path: Path) -> None:
    from deckforge.parsing.layout_kind import LayoutClassifier

    class AlwaysChart:
        def ask_image(self, **kwargs: object) -> dict[str, str]:
            return {"kind": "chart", "reason": "так решила подделка"}

    parser = TemplateParser(classifier=LayoutClassifier(vlm=AlwaysChart(), votes=1))
    manifest = parser.parse(build(tmp_path / "injected.pptx"), use_cache=False)

    # Уверенные макеты остаются за эвристикой, спорные уходят модели — и это видно.
    sources = {layout.kind_source for layout in manifest.layouts}
    assert sources <= {"heuristic", "vlm", "vlm+heuristic"}


def test_classifier_is_optional(template: Path) -> None:
    """Без VLM-клиента парсер обязан работать: это рабочий режим, а не деградация."""
    manifest = TemplateParser().parse(template, use_cache=False)
    assert {layout.kind_source for layout in manifest.layouts} == {"heuristic"}


# --- адресация макета и гарнитуры, запросы потока B --------------------------


def test_layout_knows_its_part_in_the_package(template: Path, parser: TemplateParser) -> None:
    """`index` для адресации не годится: он сквозной по мастерам и пропускает макеты
    без пригодных плейсхолдеров. `prs.slide_layouts[index]` на шаблонах кейса указывает
    не на тот макет в 34 случаях из 37. Надёжный адрес — имя части пакета."""
    manifest = parser.parse(template)
    for layout in manifest.layouts:
        assert layout.part_name.startswith("ppt/slideLayouts/")
        assert layout.part_name.endswith(".xml")
    parts = [layout.part_name for layout in manifest.layouts]
    assert len(parts) == len(set(parts)), "часть пакета обязана адресовать ровно один макет"


def test_theme_font_references_are_resolved(template: Path, parser: TemplateParser) -> None:
    """Слоям выше не должно быть дела до синтаксиса OOXML: `+mj-lt` разворачивается здесь."""
    manifest = parser.parse(template)
    fonts = {
        ph.font_family
        for layout in manifest.layouts
        for ph in layout.placeholders
        if ph.font_family
    }
    assert not any(f.startswith("+") for f in fonts), f"неразвёрнутые ссылки: {fonts}"
