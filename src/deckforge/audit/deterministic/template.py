"""Проверки соответствия шаблону (§5.1). Change (15) `audit-deterministic`.

Проверки этой группы отвечают на вопрос «этот слайд собран по правилам загруженного
шаблона?». Эталон — `TemplateManifest`, собственных представлений о «правильном»
у проверок нет: ни цвета, ни кегля, ни гарнитуры в коде не встречается (гейт C6).

Две проверки здесь работают не так, как звучат, и это следствие ADR-002.

**Цвет.** В `SlideIR` цвет выразим только ссылкой на слот темы (`ColorRef`), литерал
`#RRGGBB` запрещён схемой. Поэтому «цвет не из палитры» на уровне IR сработать не может
в принципе: любая ссылка по построению принадлежит палитре. Проверка ловит то, что
на этом уровне ещё осмысленно — ссылку на слот, которого в теме нет, и две одинаковые
ссылки на соседних сериях диаграммы. Полная проверка цвета делается по готовому файлу.

**Гарнитура.** Имени гарнитуры в IR тоже нет, а гарнитура плейсхолдера принадлежит
шаблону по построению. Чужой шрифт появляется только при записи файла — там проверка
его и ищет, если файл передан. По одному IR остаётся считать **число** гарнитур: это
уже свойство колоды, а не шаблона.
"""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import (
    FULL_BLEED_SHARE,
    block_bbox,
    carries_text,
    covers,
    layout_of,
    placeholder_of,
    positioned_blocks,
)
from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, ColorRef, Severity, TextRole
from deckforge.domain.rules import contrast_ratio
from deckforge.domain.slide import ChartBlock, KpiBlock
from deckforge.domain.template import TemplateManifest


def template_fonts(manifest: TemplateManifest) -> set[str]:
    """Гарнитуры, которые шаблон действительно использует.

    Это не только пара из темы. На шаблонах кейса тема заявляет Arial, а плейсхолдеры
    набраны Play: сверка с одной темой дала бы находку на каждом слайде — то есть
    проверку, которая врёт на эталоне и обесценивает весь отчёт.
    """
    fonts = {
        family
        for family in (manifest.theme.fonts.major_latin, manifest.theme.fonts.minor_latin)
        if family
    }
    fonts |= {
        placeholder.font_family
        for layout in manifest.layouts
        for placeholder in layout.placeholders
        if placeholder.font_family
    }
    return fonts


def _fonts_in_file(path: object) -> dict[str, list[str]]:
    """Гарнитуры, которыми набран готовый файл: `slide_id-номер` → список гарнитур.

    По `SlideIR` эту проверку сделать нельзя: имени гарнитуры в IR нет вовсе, а кегль
    и шрифт приезжают из плейсхолдера шаблона — то есть по построению «из шаблона».
    Чужая гарнитура может появиться только при записи файла, там её и надо искать.
    """
    try:
        from pptx import Presentation

        presentation = Presentation(str(path))
    except Exception:
        return {}

    found: dict[str, list[str]] = {}
    for number, slide in enumerate(presentation.slides, start=1):
        families: list[str] = []
        for shape in slide.shapes:
            frame = getattr(shape, "text_frame", None)
            if frame is None:
                continue
            for paragraph in frame.paragraphs:
                for run in paragraph.runs:
                    name = run.font.name
                    if name:
                        families.append(name)
        found[str(number)] = families
    return found


@check(id="template.font_not_in_theme", deterministic=True, severity=Severity.ERROR,
       title="Шрифт не из шаблона или гарнитур больше двух")
def font_not_in_theme(ctx: CheckContext) -> Iterable[Finding]:
    """Шрифт не из шаблона или гарнитур больше двух."""
    manifest = ctx.manifest
    known = template_fonts(manifest)
    max_families = int(ctx.param("max_families", 2))
    used: set[str] = set()

    # Гарнитуры плейсхолдеров, в которые лягут блоки: они принадлежат шаблону
    # по построению, но их **количество** — уже свойство колоды.
    for slide in ctx.deck.slides:
        layout = layout_of(slide, manifest)
        for block in slide.blocks:
            placeholder = placeholder_of(block, layout)
            family = placeholder.font_family if placeholder is not None else None
            if family is None:
                role = getattr(block, "role", None)
                step = manifest.typography(role) if isinstance(role, TextRole) else None
                family = manifest.theme.fonts.get(step.font_ref) if step is not None else None
            if family:
                used.add(family)

    slide_ids = [slide.slide_id for slide in ctx.deck.slides]
    if ctx.deck_path is not None:
        for page, families in sorted(_fonts_in_file(ctx.deck_path).items()):
            index = int(page) - 1
            slide_id = slide_ids[index] if 0 <= index < len(slide_ids) else None
            for family in sorted(set(families)):
                used.add(family)
                if family in known:
                    continue
                yield make_finding(
                    check_id="template.font_not_in_theme",
                    slide_id=slide_id,
                    reason=f"font:{family}",
                    message=(
                        f"Гарнитура «{family}» в шаблоне не встречается: "
                        + ", ".join(sorted(known))
                    ),
                    evidence={"family": family, "known": ", ".join(sorted(known))},
                )

    if len(used) > max_families:
        yield make_finding(
            check_id="template.font_not_in_theme",
            reason="too_many_families",
            message=(
                f"В колоде {len(used)} гарнитуры при допустимых {max_families}: "
                + ", ".join(sorted(used))
            ),
            evidence={"families": ", ".join(sorted(used))},
        )


def template_sizes(manifest: TemplateManifest) -> list[float]:
    """Кегли шаблона: шкала плюс фактические кегли плейсхолдеров.

    Шкала — четыре ступени по ролям, а плейсхолдеры живут своими размерами: заголовок
    раздела и заголовок слайда набраны по-разному, хотя роль у них одна. Сверять только
    со шкалой значит ругаться на кегль, который шаблон сам и задал.
    """
    sizes = set(manifest.size_ladder_pt)
    sizes |= {
        placeholder.size_pt
        for layout in manifest.layouts
        for placeholder in layout.placeholders
        if placeholder.size_pt
    }
    return sorted(sizes, reverse=True)


@check(id="template.size_not_in_scale", deterministic=True, severity=Severity.WARNING,
       title="Кегль не из типографической шкалы шаблона")
def size_not_in_scale(ctx: CheckContext) -> Iterable[Finding]:
    """Кегль не из типографической шкалы шаблона."""
    allowed = template_sizes(ctx.manifest)
    if not allowed:
        return
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            size = getattr(block, "size_pt", None)
            if size is None:
                # Кегль мог быть выбран вписыванием (change 12) — тогда он в fit_report.
                measured = slide.fit_report.get(block.block_id)
                size = measured.final_size_pt if measured is not None else None
            if size is None:
                continue
            if any(abs(size - step) < 0.01 for step in allowed):
                continue
            yield make_finding(
                check_id="template.size_not_in_scale",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason=f"size:{size:g}",
                message=(
                    f"Кегль {size:g} pt в шаблоне не встречается: "
                    + ", ".join(f"{step:g}" for step in allowed[:8])
                ),
                evidence={"size_pt": f"{size:g}"},
            )


@check(id="template.color_not_in_palette", deterministic=True, severity=Severity.ERROR,
       auto_fix=AutoFix.MAP_TO_NEAREST_THEME_COLOR, title="Цвет не из палитры шаблона")
def color_not_in_palette(ctx: CheckContext) -> Iterable[Finding]:
    """Цвет не из палитры шаблона."""
    colors = ctx.manifest.theme.colors
    known = set(colors.model_dump())

    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            refs: list[ColorRef] = []
            if isinstance(block, ChartBlock):
                refs = list(block.series_color_refs)
            elif isinstance(block, KpiBlock):
                refs = [item.color_ref for item in block.items if item.color_ref is not None]
            else:
                own = getattr(block, "color_ref", None)
                refs = [own] if isinstance(own, ColorRef) else []

            for ref in refs:
                if ref.value not in known:
                    yield make_finding(
                        check_id="template.color_not_in_palette",
                        slide_id=slide.slide_id,
                        block_id=block.block_id,
                        bbox=block_bbox(block, layout),
                        reason=f"unknown:{ref.value}",
                        message=f"Слота {ref.value} нет в палитре шаблона",
                        evidence={"color_ref": ref.value},
                    )

            # Две серии одного цвета на диаграмме неразличимы — это тот же дефект
            # палитры, только проявленный внутри одного блока.
            if isinstance(block, ChartBlock) and len(set(refs)) != len(refs):
                duplicates = sorted({ref.value for ref in refs if refs.count(ref) > 1})
                yield make_finding(
                    check_id="template.color_not_in_palette",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=block_bbox(block, layout),
                    reason="duplicate_series",
                    message=(
                        "Серии диаграммы окрашены одним цветом и неразличимы: "
                        + ", ".join(duplicates)
                    ),
                    evidence={"duplicates": ", ".join(duplicates)},
                )


def _layout_parts_in_file(ctx: CheckContext) -> list[str] | None:
    """Имена частей макетов, на которых собраны слайды готового файла.

    Адресоваться к макету по индексу нельзя: `LayoutSpec.index` сквозной по мастерам,
    а макеты без пригодных плейсхолдеров пропущены. На шаблонах кейса `slide_layouts[index]`
    промахивается в 34 случаях из 37 — поэтому сверка идёт по `part_name`.
    """
    path = ctx.deck_path
    if path is None:
        return None
    try:
        from pptx import Presentation

        presentation = Presentation(str(path))
    except Exception:
        return None
    return [str(slide.slide_layout.part.partname).lstrip("/") for slide in presentation.slides]


@check(id="template.layout_not_from_template", deterministic=True, severity=Severity.ERROR,
       title="Слайд собран не на макете из шаблона")
def layout_not_from_template(ctx: CheckContext) -> Iterable[Finding]:
    """Слайд собран не на макете из шаблона."""
    parts_in_file = _layout_parts_in_file(ctx)
    if parts_in_file is not None:
        for number, slide in enumerate(ctx.deck.slides):
            if number >= len(parts_in_file):
                break
            declared = layout_of(slide, ctx.manifest)
            actual = parts_in_file[number]
            if declared is None or declared.part_name.lstrip("/") == actual:
                continue
            yield make_finding(
                check_id="template.layout_not_from_template",
                slide_id=slide.slide_id,
                reason=f"part:{actual}",
                message=(
                    f"Слайд собран на макете {actual}, а план объявлял "
                    f"{declared.part_name} ({declared.layout_id})"
                ),
                evidence={"expected": declared.part_name, "actual": actual},
            )

    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        if layout is None:
            yield make_finding(
                check_id="template.layout_not_from_template",
                slide_id=slide.slide_id,
                reason=f"layout:{slide.layout_id}",
                message=(
                    f"Макета {slide.layout_id} нет в шаблоне: доступны "
                    + ", ".join(item.layout_id for item in ctx.manifest.layouts)
                ),
                evidence={"layout_id": slide.layout_id},
            )
            continue

        for block in slide.blocks:
            idx = getattr(block, "placeholder_idx", None)
            if idx is None or layout.placeholder(idx) is not None:
                continue
            yield make_finding(
                check_id="template.layout_not_from_template",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                reason=f"placeholder:{idx}",
                message=(
                    f"Блок {block.block_id} ссылается на плейсхолдер {idx}, "
                    f"которого нет в макете {layout.layout_id}"
                ),
                evidence={"layout_id": layout.layout_id, "placeholder_idx": str(idx)},
            )


@check(id="template.decor_moved", deterministic=True, severity=Severity.WARNING,
       title="Логотип или колонтитул сдвинуты с положенного места")
def decor_moved(ctx: CheckContext) -> Iterable[Finding]:
    """Логотип или колонтитул сдвинуты с положенного места."""
    tolerance = int(ctx.param("tolerance_emu", 0))
    slide_box = ctx.manifest.slide_size.bbox
    logo = ctx.manifest.decor.logo

    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)

        # Декор макета — фигуры вне плейсхолдеров: знак, плашка, подпись. Без них
        # декор для аудита невидим, и «накрыли логотип» не поймать (kickoff C-15).
        decor_boxes: list[tuple[str, object]] = []
        if logo is not None:
            decor_boxes.append(("логотип шаблона", logo.bbox))
        if layout is not None:
            decor_boxes += [
                (f"декор макета {shape.shape_id}", shape.bbox)
                for shape in layout.shapes
                # Фон во весь слайд лежит под контентом по замыслу, а не по ошибке.
                if not covers(shape.bbox, slide_box, FULL_BLEED_SHARE)
            ]
        if not decor_boxes:
            continue

        for block, bbox in positioned_blocks(slide, ctx.manifest):
            # Сдвинуть декор из IR нельзя — он приезжает с мастера (ADR-002).
            # Испортить его можно единственным способом: накрыть своим блоком.
            for label, decor_box in decor_boxes:
                overlap = bbox.intersection_area(decor_box)  # type: ignore[arg-type]
                if overlap <= tolerance:
                    continue
                yield make_finding(
                    check_id="template.decor_moved",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=bbox,
                    reason=f"covered:{label}",
                    message=f"Блок {block.block_id} накрывает {label}",
                    evidence={"overlap_emu2": str(overlap), "decor": label},
                )


@check(id="template.contrast_below_wcag", deterministic=True, severity=Severity.ERROR,
       title="Контраст текста к фону ниже 4.5:1")
def contrast_below_wcag(ctx: CheckContext) -> Iterable[Finding]:
    """Контраст текста к фону ниже 4.5:1."""
    manifest = ctx.manifest
    colors = manifest.theme.colors
    min_ratio = ctx.param("min_ratio", 4.5)
    min_ratio_large = ctx.param("min_ratio_large", 3.0)
    large_text_pt = ctx.param("large_text_pt", 18.0)

    # Фон макета манифест пока не описывает (см. proposal, «что осталось незакрытым»),
    # поэтому сравнение идёт со светлым слотом темы. На тёмном макете такой вердикт
    # неполон, и это указано в evidence, а не выдано за полноценную проверку.
    background = colors.get(ColorRef.LT1)

    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            if not carries_text(block):
                continue
            ref = getattr(block, "color_ref", None)
            if not isinstance(ref, ColorRef):
                continue
            role = getattr(block, "role", None)
            size = getattr(block, "size_pt", None)
            if size is None and isinstance(role, TextRole):
                step = manifest.typography(role)
                size = step.size_pt if step is not None else None

            foreground = colors.get(ref)
            ratio = contrast_ratio(foreground, background)
            is_large = size is not None and size >= large_text_pt
            threshold = min_ratio_large if is_large else min_ratio
            if ratio >= threshold:
                continue
            yield make_finding(
                check_id="template.contrast_below_wcag",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason=f"contrast:{ref.value}",
                message=(
                    f"Контраст текста блока {block.block_id} к фону {ratio:.1f}:1 "
                    f"при требуемых {threshold:.1f}:1"
                ),
                evidence={
                    "foreground": foreground,
                    "background": background,
                    "background_source": "тема lt1: фон макета в манифесте пока не описан",
                    "ratio": f"{ratio:.2f}",
                },
            )
