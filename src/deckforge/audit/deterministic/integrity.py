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
from typing import Any

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import block_bbox, block_text, layout_of, slide_text
from deckforge.audit.recipes import catalogue_with_passports
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.designsystem.models import PlaceKind, Recipe
from deckforge.domain.audit import Finding
from deckforge.domain.enums import ChartType, Severity, TextRole
from deckforge.domain.slide import ChartBlock, IconBlock, ImageBlock, SlideIR, TextBlock

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


@check(id="integrity.content_lost", deterministic=True, severity=Severity.ERROR,
       title="От слайда остался один заголовок, хотя план дал ему факты")
def content_lost(ctx: CheckContext) -> Iterable[Finding]:
    """От слайда остался один заголовок, хотя план дал ему факты.

    Это не то же, что `integrity.empty_slide`. Тот пропускает слайд, у макета которого
    нет места под текст (`max_chars_body == 0`), — титул и перебивка из одного заголовка
    состоят по замыслу. 19.09 из-за этого прошла колода, где **все двенадцать** слайдов
    легли на макет с единственным плейсхолдером-заголовком: композиция отбросила блоки,
    которым не нашлось места, и «слайд по замыслу без текста» стало неотличимо
    от «слайда, у которого текст потеряли».

    Различает их план. Факты, отданные слайду планировщиком, едут в `provenance.fact_refs`.
    Были факты, а на слайде ни одного содержательного блока — контент потерян, и это
    ошибка независимо от того, что позволяет макет.

    Картинка и иконка содержанием не считаются: слайд из одних картинок не засчитывается
    и по ТЗ (C3, `integrity.slide_is_image`), а факт, который нигде не написан, ею
    не передан.
    """
    for slide in ctx.deck.slides:
        if not slide.provenance.fact_refs:
            continue
        substance = [block for block in slide.blocks if _is_substance(block)]
        if substance:
            continue
        yield make_finding(
            check_id="integrity.content_lost",
            slide_id=slide.slide_id,
            reason="facts_dropped",
            message=(
                f"На слайде только заголовок, хотя план дал ему "
                f"{len(slide.provenance.fact_refs)} факт(ов): содержание потеряно"
            ),
            evidence={
                "fact_refs": ", ".join(slide.provenance.fact_refs),
                "blocks": ", ".join(block.block_id for block in slide.blocks) or "нет",
            },
        )


def _is_substance(block: object) -> bool:
    """Блок несёт содержание слайда, а не оформляет его."""
    if isinstance(block, ImageBlock | IconBlock):
        return False
    return not (isinstance(block, TextBlock) and block.role is TextRole.TITLE)


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

            by_recipe = bool(slide.recipe_id) and bool(other.recipe_id)
            if distance is not None and not by_recipe:
                # Есть на что смотреть: решает картинка. Одинаковый текст на разных
                # макетах даёт разные слайды, и дублем это не считается.
                same = distance <= hash_threshold
                why = f"изображения совпадают (расстояние {distance})"
                note = ""
            elif by_recipe:
                # Оба слайда по рецепту: хеш меряет композицию примера — фон, плашки,
                # сетку карточек, — а не содержание (RG61). В прогоне `96ef159` все
                # 12 «дублей» были слайдами на одном виде рецепта с совпадением текста
                # 0–25 %. Решает текст, тем же порогом, что и без превью.
                same = similarity >= text_threshold
                why = (
                    f"совпадение текста {similarity:.0%} "
                    "(слайды по рецепту: картинка меряет рецепт)"
                )
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
                    "compared": (
                        "только текст"
                        if distance is None
                        else "текст" if by_recipe else "изображение"
                    ),
                },
            )


# --- пустая группа примера (план Б, RG63, change `the-empty-card-is-found`) ---------------

#: Фигуры страницы, у которых есть `cNvPr id`: по нему фигура слайда узнаётся в примере.
_SHAPE_TAGS = ("sp", "pic", "cxnSp", "grpSp", "graphicFrame")


def _page_shapes(page: Any) -> dict[int, str]:
    """Фигуры страницы по `cNvPr id` → их текст (пустая строка — фигура без текста)."""
    from pptx.oxml.ns import qn

    tags = {qn(f"p:{tag}") for tag in _SHAPE_TAGS}
    found: dict[int, str] = {}
    for node in page.shapes._spTree.iter():
        if node.tag not in tags:
            continue
        props = node.find(f"./*/{qn('p:cNvPr')}")
        if props is None or not (props.get("id") or "").isdigit():
            continue
        found[int(props.get("id"))] = "".join(t.text or "" for t in node.iter(qn("a:t"))).strip()
    return found


def _empty_groups(recipe: Recipe, shapes: dict[int, str], authored: dict[int, int]) -> list[
    tuple[str, str | None]
]:
    """Группы рецепта, которые остались на странице без текста: (группа, ряд).

    Группа паспорта — карточка, пункт схемы: её фигуры (декор и рамки мест) живут и уходят
    вместе. Осталась хоть одна, а текста нет ни в одном месте — на слайде пустая карточка.
    Пусто и у автора — его композиция (RG36), не наша. Без паспорта — повторы каталога.
    """
    if recipe.passport is not None:
        units = [
            (
                group.group_id,
                group.row,
                [*group.decor_xml_ids, *(p.xml_id for p in group.places if p.xml_id)],
                [p.xml_id for p in group.places if p.kind is not PlaceKind.PICTURE and p.xml_id],
            )
            for group in recipe.passport.groups
        ]
    else:
        units = [
            (
                f"repeat{index}",
                None,
                list(addresses),
                [z.xml_id for z in recipe.zones if z.repeat == index and z.xml_id is not None],
            )
            for index, addresses in enumerate(recipe.repeat_xml_ids)
        ]
    empty: list[tuple[str, str | None]] = []
    for unit, row, members, places in units:
        if not places or not any(member in shapes for member in members):
            continue
        if any(shapes.get(place) for place in places):
            continue
        if not any(authored.get(place, 0) for place in places):
            continue
        empty.append((unit, row))
    return empty


@check(id="integrity.empty_group", deterministic=True, severity=Severity.WARNING,
       title="На слайде осталась пустая карточка примера")
def empty_group(ctx: CheckContext) -> Iterable[Finding]:
    """На слайде осталась пустая карточка примера (план Б, строка 3; RG63).

    Судья-VLM видел пустые карточки на 5 слайдах VK Tech из 10, детерминированные проверки
    молчали: пустая у автора рамка — его композиция (RG36). Отличает нашу пустоту от чужой
    паспорт примера: группа мест, которую мы должны были заполнить или снять целиком, осталась
    на странице без текста. Пусто и у автора — не находка.

    Меряется **готовый файл** против паспорта — контракта A ↔ B, а не решение писателя:
    замер не подтверждает сам себя. Паспорт — из дизайн-системы или считается по снимку
    (`catalogue_with_passports`); пример без паспорта сверяется по повторам каталога.
    Страница — по номеру слайда в IR, как у `template.sample_text_left`.
    """
    path = ctx.deck_path
    if path is None:
        raise CheckUnavailable("файла колоды ещё нет: пустая карточка видна только в .pptx")
    if not ctx.manifest.examples:
        raise CheckUnavailable("в шаблоне нет слайдов-примеров: карточек примера не бывает")
    recipe_ids = {slide.recipe_id for slide in ctx.deck.slides if slide.recipe_id}
    if not recipe_ids:
        raise CheckUnavailable("ни одного слайда по рецепту: карточек примера нет")
    try:
        from pptx import Presentation

        pages = list(Presentation(str(path)).slides)
    except Exception as error:
        raise CheckUnavailable(f"файл колоды не открылся: {type(error).__name__}") from error
    if len(pages) < len(ctx.deck.slides):
        raise CheckUnavailable(
            f"в файле {len(pages)} слайдов, а в IR {len(ctx.deck.slides)}: "
            "страницу слайда по рецепту не найти"
        )

    recipes = catalogue_with_passports(ctx)
    examples = {example.slide_index: example for example in ctx.manifest.examples}
    for page, slide in zip(pages, ctx.deck.slides, strict=False):
        recipe = recipes.get(slide.recipe_id or "")
        example = examples.get(recipe.example_index) if recipe is not None else None
        if recipe is None or example is None:
            continue
        authored = {s.xml_id: s.text_len for s in example.shapes if s.xml_id is not None}
        for unit, row in _empty_groups(recipe, _page_shapes(page), authored):
            where = f" ряда {row}" if row else ""
            yield make_finding(
                check_id="integrity.empty_group",
                slide_id=slide.slide_id,
                reason=f"empty_group:{recipe.recipe_id}:{unit}",
                message=(
                    f"Карточка {unit}{where} примера {recipe.recipe_id} осталась на слайде "
                    "без текста: её надо было заполнить или снять целиком"
                ),
                evidence={"recipe_id": recipe.recipe_id, "group": unit, "row": row or ""},
            )
