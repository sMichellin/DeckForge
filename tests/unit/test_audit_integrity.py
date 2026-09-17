"""Проверки целостности: на нарушителе и на норме. Change (15)."""

from __future__ import annotations

import io
import random
from pathlib import Path

import pytest

from deckforge.audit.deterministic.integrity import (
    chart_labels_missing,
    duplicate_slides,
    empty_slide,
    file_opens,
    placeholder_text,
    slide_is_image,
)
from deckforge.audit.registry import CheckUnavailable
from deckforge.domain.enums import ChartType
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import (
    body,
    bullets,
    chart,
    context_for,
    deck,
    image,
    slide,
    title,
)


def test_file_opens_catches_a_broken_file(manifest: TemplateManifest, tmp_path: Path) -> None:
    broken = tmp_path / "deck.pptx"
    broken.write_bytes(b"not a presentation")
    colony = deck(slide(title()))
    context = context_for("integrity.file_opens", colony, manifest, deck_path=broken)
    findings = list(file_opens(context))
    assert len(findings) == 1
    assert "не открывается" in findings[0].message


def test_file_opens_silent_on_a_valid_file(manifest: TemplateManifest, tmp_path: Path) -> None:
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "deck.pptx"
    presentation = pptx.Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(str(path))

    colony = deck(slide(title()))
    context = context_for("integrity.file_opens", colony, manifest, deck_path=path)
    assert list(file_opens(context)) == []


def test_file_opens_is_unavailable_without_a_path(manifest: TemplateManifest) -> None:
    """Файла ещё нет — это пропуск, а не «проверка пройдена»."""
    colony = deck(slide(title()))
    with pytest.raises(CheckUnavailable):
        list(file_opens(context_for("integrity.file_opens", colony, manifest)))


def test_placeholder_text_catches_a_leftover(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("TODO дописать вывод")))
    findings = list(placeholder_text(context_for("integrity.placeholder_text", colony, manifest)))
    assert [f.evidence["match"] for f in findings] == ["TODO"]


def test_placeholder_text_silent_on_real_content(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("Выручка выросла за счёт одного канала")))
    context = context_for("integrity.placeholder_text", colony, manifest)
    assert list(placeholder_text(context)) == []


def test_empty_slide_catches_a_title_only_content_slide(manifest: TemplateManifest) -> None:
    colony = deck(slide(title()))
    findings = list(empty_slide(context_for("integrity.empty_slide", colony, manifest)))
    assert [f.slide_id for f in findings] == ["s01"]


def test_empty_slide_allows_a_title_layout(manifest: TemplateManifest) -> None:
    """У макета `L01` вместимость тела нулевая: заголовок там и есть всё содержание."""
    colony = deck(slide(title(), layout_id="L01"))
    assert list(empty_slide(context_for("integrity.empty_slide", colony, manifest))) == []


def test_empty_slide_silent_when_there_is_content(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), bullets("первое", "второе")))
    assert list(empty_slide(context_for("integrity.empty_slide", colony, manifest))) == []


def test_slide_is_image_catches_a_picture_only_slide(manifest: TemplateManifest) -> None:
    colony = deck(slide(image()))
    findings = list(slide_is_image(context_for("integrity.slide_is_image", colony, manifest)))
    assert [f.slide_id for f in findings] == ["s01"]


def test_slide_is_image_silent_when_text_is_present(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), image()))
    assert list(slide_is_image(context_for("integrity.slide_is_image", colony, manifest))) == []


def test_chart_labels_missing_catches_a_chart_without_axes(manifest: TemplateManifest) -> None:
    colony = deck(slide(chart(axis_titles={})))
    context = context_for("integrity.chart_labels_missing", colony, manifest)
    findings = list(chart_labels_missing(context))
    assert "подписи осей" in findings[0].evidence["missing"]


def test_chart_labels_missing_allows_a_doughnut_without_axes(
    manifest: TemplateManifest,
) -> None:
    """У круговой диаграммы осей нет — требовать их подписи бессмысленно."""
    colony = deck(slide(chart(chart_type=ChartType.DOUGHNUT, axis_titles={})))
    context = context_for("integrity.chart_labels_missing", colony, manifest)
    assert list(chart_labels_missing(context)) == []


def test_chart_labels_missing_silent_on_a_labelled_chart(manifest: TemplateManifest) -> None:
    colony = deck(slide(chart(axis_titles={"value": "млн ₽", "category": "Квартал"})))
    context = context_for("integrity.chart_labels_missing", colony, manifest)
    assert list(chart_labels_missing(context)) == []


def _png(seed: int) -> bytes:
    """Превью, различимое перцептивным хешом. Одно зерно — одна и та же картинка.

    Простые фигуры для такого теста не годятся: хеш строится на низких частотах,
    и «левая половина чёрная» против «верхняя половина чёрная» дают расстояние 4
    при пороге 6 — то есть считаются одним изображением. Одноцветные заливки
    неразличимы тем более. Поэтому здесь детерминированный шум: разные зёрна дают
    заведомо разные картинки, одинаковые — побайтово совпадающие.
    """
    image_mod = pytest.importorskip("PIL.Image")
    rng = random.Random(seed)
    pixels = bytes(rng.getrandbits(8) for _ in range(64 * 64 * 3))
    buffer = io.BytesIO()
    image_mod.frombytes("RGB", (64, 64), pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def test_duplicate_slides_catches_the_same_picture_under_different_text(
    manifest: TemplateManifest,
) -> None:
    """Одна фотография с разными подписями — дубль по смыслу, по словам непохожий."""
    picture = _png(1)
    colony = deck(
        slide(title("Выручка выросла на треть"), slide_id="s01"),
        slide(title("Затраты снизились вдвое"), slide_id="s02"),
    )
    context = context_for(
        "integrity.duplicate_slides",
        colony,
        manifest,
        previews={"s01": picture, "s02": picture},
    )
    findings = list(duplicate_slides(context))
    assert [f.evidence["other_slide_id"] for f in findings] == ["s01"]
    assert findings[0].evidence["compared"] == "изображение"


def test_duplicate_slides_silent_when_pictures_differ(manifest: TemplateManifest) -> None:
    """Одинаковый текст на разных макетах выглядит по-разному и дублем не является."""
    text = "Выручка выросла на треть за счёт одного канала"
    colony = deck(
        slide(title(text), slide_id="s01"),
        slide(title(text), slide_id="s02", layout_id="L01"),
    )
    context = context_for(
        "integrity.duplicate_slides",
        colony,
        manifest,
        previews={"s01": _png(1), "s02": _png(2)},
    )
    assert list(duplicate_slides(context)) == []


def test_duplicate_slides_admits_the_comparison_was_partial(
    manifest: TemplateManifest,
) -> None:
    """Превью нет — сравниваем текст и говорим об этом в находке, а не молчим."""
    text = "Выручка выросла на треть за счёт одного канала"
    colony = deck(slide(title(text), slide_id="s01"), slide(title(text), slide_id="s02"))
    findings = list(
        duplicate_slides(context_for("integrity.duplicate_slides", colony, manifest))
    )
    assert findings[0].evidence["compared"] == "только текст"
    assert "неполное" in findings[0].message


def test_duplicate_slides_catches_a_repeated_slide(manifest: TemplateManifest) -> None:
    text = "Выручка выросла на треть за счёт одного канала"
    colony = deck(
        slide(title(text), slide_id="s01"),
        slide(title(text), slide_id="s02"),
    )
    findings = list(duplicate_slides(context_for("integrity.duplicate_slides", colony, manifest)))
    assert [f.evidence["other_slide_id"] for f in findings] == ["s01"]


def test_duplicate_slides_silent_on_different_slides(manifest: TemplateManifest) -> None:
    colony = deck(
        slide(title("Выручка выросла на треть"), slide_id="s01"),
        slide(title("Затраты снизились вдвое"), slide_id="s02"),
    )
    assert list(duplicate_slides(context_for("integrity.duplicate_slides", colony, manifest))) == []
