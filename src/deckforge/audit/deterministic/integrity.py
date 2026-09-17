"""Проверки целостности (§5.1). `integrity.slide_is_image` — машинная защита C3.

Три проверки этой группы смотрят на готовый файл, а не на IR: открывается ли он,
не оказался ли слайд картинкой, не совпали ли два слайда по изображению. До change (13)
файла не существует, и тогда проверка **ничего не возвращает и попадает в пропущенные**
(`AuditRunner.skipped_checks`). «Не проверяли» и «нарушений нет» — разные состояния,
и отчёт обязан их различать.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import block_bbox, block_text, layout_of, slide_text
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import ChartType, Severity, TextRole
from deckforge.domain.slide import ChartBlock, ImageBlock, SlideIR, TextBlock

#: Заглушки, которые остаются от шаблонов промптов и от ручной правки.
_PLACEHOLDER_PATTERN = r"lorem ipsum|\bTODO\b|\bXXX\b|вставьте текст|\bTBD\b"

#: Круговым диаграммам оси не нужны — у них их нет.
_AXISLESS = (ChartType.PIE, ChartType.DOUGHNUT)


@check(id="integrity.file_opens", deterministic=True, severity=Severity.ERROR,
       title="Файл не открывается")
def file_opens(ctx: CheckContext) -> Iterable[Finding]:
    """Файл не открывается."""
    path = ctx.deck_path
    if path is None:
        raise CheckUnavailable("файла колоды ещё нет: открывать нечего")
    try:
        from pptx import Presentation

        Presentation(str(path))
    except Exception as error:
        yield make_finding(
            check_id="integrity.file_opens",
            reason="open_failed",
            message=f"Файл колоды не открывается: {type(error).__name__}: {error}",
            evidence={"path": str(path)},
        )


@check(id="integrity.placeholder_text", deterministic=True, severity=Severity.ERROR,
       title="Остался текст-заглушка: lorem ipsum, XXX, TODO")
def placeholder_text(ctx: CheckContext) -> Iterable[Finding]:
    """Остался текст-заглушка: lorem ipsum, XXX, TODO."""
    pattern = re.compile(ctx.text_param("pattern", _PLACEHOLDER_PATTERN), re.IGNORECASE)
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            match = pattern.search(block_text(block))
            if match is None:
                continue
            yield make_finding(
                check_id="integrity.placeholder_text",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason=f"placeholder:{match.group(0).lower()}",
                message=f"В блоке {block.block_id} осталась заглушка «{match.group(0)}»",
                evidence={"match": match.group(0)},
            )


@check(id="integrity.empty_slide", deterministic=True, severity=Severity.ERROR,
       title="Пустой слайд или слайд с одним заголовком")
def empty_slide(ctx: CheckContext) -> Iterable[Finding]:
    """Пустой слайд или слайд с одним заголовком."""
    for slide in ctx.deck.slides:
        if not slide.blocks:
            yield make_finding(
                check_id="integrity.empty_slide",
                slide_id=slide.slide_id,
                reason="no_blocks",
                message="На слайде нет ни одного блока",
            )
            continue

        # Титул и перебивка состоят из заголовка по замыслу — это не пустой слайд.
        layout = layout_of(slide, ctx.manifest)
        if layout is not None and layout.capacity.max_chars_body == 0:
            continue
        meaningful = [
            block
            for block in slide.blocks
            if not (isinstance(block, TextBlock) and block.role is TextRole.TITLE)
        ]
        if meaningful:
            continue
        yield make_finding(
            check_id="integrity.empty_slide",
            slide_id=slide.slide_id,
            reason="title_only",
            message="На слайде только заголовок: содержания нет",
        )


@check(id="integrity.slide_is_image", deterministic=True, severity=Severity.ERROR,
       title="C3: слайд оказался картинкой, а не редактируемыми объектами")
def slide_is_image(ctx: CheckContext) -> Iterable[Finding]:
    """C3: слайд оказался картинкой, а не редактируемыми объектами."""
    for slide in ctx.deck.slides:
        if not slide.blocks:
            continue
        if not all(isinstance(block, ImageBlock) for block in slide.blocks):
            continue
        yield make_finding(
            check_id="integrity.slide_is_image",
            slide_id=slide.slide_id,
            reason="only_images",
            message=(
                "Слайд состоит только из изображений: по ТЗ такой слайд не засчитывается, "
                "объекты должны быть редактируемыми"
            ),
            evidence={"blocks": str(len(slide.blocks))},
        )


@check(id="integrity.chart_labels_missing", deterministic=True, severity=Severity.WARNING,
       title="У диаграммы нет подписей осей, единиц или легенды")
def chart_labels_missing(ctx: CheckContext) -> Iterable[Finding]:
    """У диаграммы нет подписей осей, единиц или легенды."""
    content = ctx.content
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            if not isinstance(block, ChartBlock):
                continue

            missing: list[str] = []
            if block.chart_type not in _AXISLESS and not block.axis_titles:
                missing.append("подписи осей")

            dataset = content.dataset(block.dataset_ref) if content is not None else None
            series_count = len(dataset.series) if dataset is not None else 0
            if series_count > 1 and not block.legend:
                missing.append("легенда при нескольких сериях")
            if dataset is not None and not dataset.unit and "value" not in block.axis_titles:
                missing.append("единицы измерения")

            if not missing:
                continue
            yield make_finding(
                check_id="integrity.chart_labels_missing",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason="labels:" + ",".join(missing),
                message=f"У диаграммы {block.block_id} не хватает: " + ", ".join(missing),
                evidence={"missing": ", ".join(missing)},
            )


def _text_vector(slide: SlideIR) -> Counter[str]:
    return Counter(re.findall(r"\w+", slide_text(slide).lower()))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    numerator = sum(left[word] * right[word] for word in shared)
    norm = math.sqrt(sum(v * v for v in left.values())) * math.sqrt(
        sum(v * v for v in right.values())
    )
    return numerator / norm if norm else 0.0


def _perceptual_hashes(previews: dict[str, bytes]) -> dict[str, object]:
    """Перцептивные хеши превью: `slide_id` → хеш. Пусто, если считать нечем.

    Импорт внутри функции: без превью библиотека не нужна вовсе, а её отсутствие
    не должно ронять реестр проверок при импорте модуля.
    """
    if not previews:
        return {}
    try:
        import io

        import imagehash
        from PIL import Image
    except ImportError:
        return {}

    hashes: dict[str, object] = {}
    for slide_id, raw in previews.items():
        try:
            with Image.open(io.BytesIO(raw)) as image:
                hashes[slide_id] = imagehash.phash(image)
        except Exception:
            continue
    return hashes


@check(id="integrity.duplicate_slides", deterministic=True, severity=Severity.WARNING,
       title="Два слайда дублируют друг друга")
def duplicate_slides(ctx: CheckContext) -> Iterable[Finding]:
    """Два слайда дублируют друг друга.

    Текст и картинка отвечают на разные вопросы, поэтому решают вместе.

    Два слайда с одной фотографией во весь слайд и разными подписями — дубль по смыслу,
    но по словам непохожи: текстовое сравнение их пропустит. Обратное тоже бывает:
    одинаковый текст на разных макетах выглядит по-разному и дублем не является.

    Превью приходят из change (6) и есть не всегда: в CI LibreOffice не поднимается.
    Тогда проверка не молчит и не падает — она сравнивает тексты и честно говорит
    в находке, что сравнение было неполным.
    """
    text_threshold = ctx.param("text_cosine", 0.92)
    hash_threshold = int(ctx.param("phash_distance", 6))
    slides = list(ctx.deck.slides)
    vectors = {slide.slide_id: _text_vector(slide) for slide in slides}
    hashes = _perceptual_hashes(ctx.previews)
    visual = len(hashes) >= 2

    for index, slide in enumerate(slides):
        for other in slides[index + 1 :]:
            similarity = _cosine(vectors[slide.slide_id], vectors[other.slide_id])
            distance: int | None = None
            left, right = hashes.get(slide.slide_id), hashes.get(other.slide_id)
            if left is not None and right is not None:
                distance = int(left - right)  # type: ignore[operator]

            if distance is not None:
                # Есть на что смотреть: решает картинка. Одинаковый текст на разных
                # макетах даёт разные слайды, и дублем это не считается.
                same = distance <= hash_threshold
                why = f"изображения совпадают (расстояние {distance})"
                note = ""
            else:
                same = similarity >= text_threshold
                why = f"совпадение текста {similarity:.0%}"
                note = (
                    " Сравнение неполное: превью слайдов недоступны, "
                    "картинки не сравнивались."
                    if not visual
                    else ""
                )
            if not same:
                continue

            yield make_finding(
                check_id="integrity.duplicate_slides",
                slide_id=other.slide_id,
                reason=f"duplicate:{slide.slide_id}",
                message=f"Слайд {other.slide_id} повторяет {slide.slide_id}: {why}.{note}",
                evidence={
                    "other_slide_id": slide.slide_id,
                    "cosine": f"{similarity:.3f}",
                    "phash_distance": str(distance) if distance is not None else "нет превью",
                    "compared": "изображение" if distance is not None else "только текст",
                },
            )
