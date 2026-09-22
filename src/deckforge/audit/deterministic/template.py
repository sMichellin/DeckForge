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
    self_positioned_blocks,
)
from deckforge.audit.registry import CheckContext, check
from deckforge.designsystem.contrast import (
    TextClass,
    comfort_ratio,
    required_ratio,
    text_class,
)
from deckforge.domain.audit import Finding
from deckforge.domain.base import BBox
from deckforge.domain.enums import AutoFix, ColorRef, Severity, TextRole
from deckforge.domain.rules import contrast_ratio
from deckforge.domain.slide import ChartBlock, KpiBlock
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.rendering.theme_binding import font_family_for_token

#: Доля своей площади, начиная с которой фигура макета считается лежащей в области
#: контента, — то есть подложкой под содержание, а не знаком в полях. Величина
#: безразмерная и от шаблона не зависит: это про приём, а не про бренд.
IN_CONTENT_SHARE = 0.5


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
    # Слайды-примеры — третий и самый честный источник: там видно, чем шаблон набран
    # на самом деле. У VK Tech Play стоит на 666 фигурах примеров, а тема зовёт Arial
    # (change `design-system-from-examples`, DS2).
    fonts |= {usage.family for usage in manifest.usage.fonts if usage.family}
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
            for written in sorted(set(families)):
                # В файле `typeface` бывает ссылкой на тему («+mn-lt»), а не названием
                # гарнитуры. Без разрешения ссылки проверка выдаёт ошибку на каждом
                # прогоне и заодно считает ссылку и сам шрифт двумя разными гарнитурами.
                family = font_family_for_token(written, manifest) or written
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
    """Логотип или колонтитул сдвинуты с положенного места.

    Проверка отвечает на два вопроса по отдельности, и прежде путала их (C12:
    19 предупреждений из 35 на каждом прогоне VK WorkSpace, ни одного про логотип).

    **Что защищаем — знак, а не подложку.** `LayoutSpec.shapes` по своему описанию
    «фон, фотографии, декор»: на трёх шаблонах кейса 13 из 34, 36 из 76 и 28 из 28
    таких фигур лежат внутри области контента и занимают до 76 % слайда. Это подложка
    под содержание — решатель ставит текст ровно туда, и иначе на VK WorkSpace ставить
    его будет некуда. Знак шаблон держит **в полях**, поэтому защищается фигура,
    которая в область контента заходит меньше чем наполовину. Логотип защищён всегда:
    парсер отличает его от прочих картинок мастера по построению (мелкий, у края).

    **Что значит «накрыл» — скрыл, а не задел краем.** Порог — доля площади знака,
    как `min_overlap_ratio` у `layout.overlap`. Прежний `tolerance_emu` был длиной
    и сравнивался с площадью в EMU², то есть с нулём.
    """
    min_ratio = ctx.param("min_cover_ratio", 0.5)
    slide_box = ctx.manifest.slide_size.bbox
    content = ctx.manifest.content_bbox
    logo = ctx.manifest.decor.logo

    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)

        decor_boxes: list[tuple[str, BBox]] = []
        if logo is not None:
            decor_boxes.append(("логотип шаблона", logo.bbox))
        if layout is not None:
            decor_boxes += [
                (f"декор макета {shape.shape_id}", shape.bbox)
                for shape in layout.shapes
                # Фон во весь слайд лежит под контентом по замыслу, а не по ошибке.
                if not covers(shape.bbox, slide_box, FULL_BLEED_SHARE)
                and content.intersection_area(shape.bbox) < IN_CONTENT_SHARE * shape.bbox.area
            ]
        if not decor_boxes:
            continue

        # Плейсхолдер, наложенный на декор, — так нарисован сам шаблон. Наша вина
        # начинается там, где мы поставили блок своими координатами.
        for block, bbox in self_positioned_blocks(slide, ctx.manifest):
            # Сдвинуть декор из IR нельзя — он приезжает с мастера (ADR-002).
            # Испортить его можно единственным способом: накрыть своим блоком.
            for label, decor_box in decor_boxes:
                if decor_box.area <= 0:
                    continue
                ratio = bbox.intersection_area(decor_box) / decor_box.area
                if ratio < min_ratio:
                    continue
                yield make_finding(
                    check_id="template.decor_moved",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=bbox,
                    reason=f"covered:{label}",
                    message=f"Блок {block.block_id} накрывает {label} на {ratio:.0%} площади",
                    evidence={"ratio": f"{ratio:.3f}", "decor": label},
                )


#: Какой параметр проверки задаёт минимум какого класса текста. Класс выбирает слой
#: `designsystem.contrast`, значение — `configs/audit_checks.yaml`. У подписи минимум
#: тот же, что у обычного текста: отличается она только запасом.
CONTRAST_PARAM: dict[TextClass, str] = {
    TextClass.BODY: "body",
    TextClass.CAPTION: "body",
    TextClass.LARGE: "large",
    TextClass.GRAPHICS: "graphics",
}


def contrast_thresholds(ctx: CheckContext) -> dict[TextClass, float]:
    """Минимум контраста по классу текста: значение из конфига, по умолчанию — слоя ДС.

    Значения по умолчанию берутся у `designsystem.contrast.required_ratio`, а не пишутся
    здесь второй раз: если параметр пропал из YAML, проверка съезжает на правило слоя,
    а не на собственное число.
    """
    return {kind: ctx.param(CONTRAST_PARAM[kind], required_ratio(kind)) for kind in TextClass}


def block_text_classes(block: object, manifest: TemplateManifest) -> tuple[TextClass, TextClass]:
    """Два ответа слоя ДС о блоке: чей минимум он обязан взять и чей запас ему нужен.

    Минимум решают кегль и начертание (`text_class` без роли): текст от 18 pt или
    от 14 pt полужирным читается при 3,0, какой бы ролью его ни назвали. Запас решает
    роль (`text_class` с ролью): подпись просит комфортный порог слоя сверх минимума.
    Разнесено не случайно: у VK Education подпись набрана 18 pt, и роль вперёд кегля
    дала бы ей минимум 4,5 — 14 из 144 пар «слот × фон» этого шаблона из нормы стали бы
    ошибками. Требование change — «от 18 pt порог 3,0», а подписи — замечание о запасе.

    Кегль — свой у блока, иначе ступени шкалы по роли; начертание — всегда ступени:
    в IR полужирного нет, его задаёт шаблон.
    """
    role = getattr(block, "role", None)
    role = role if isinstance(role, TextRole) else None
    step = manifest.typography(role) if role is not None else None
    size = getattr(block, "size_pt", None)
    if size is None and step is not None:
        size = step.size_pt
    bold = bool(step is not None and step.bold)
    return text_class(size, bold=bold), text_class(size, bold=bold, role=role)


@check(id="template.contrast_below_wcag", deterministic=True, severity=Severity.ERROR,
       title="Контраст текста к фону ниже порога своего класса")
def contrast_below_wcag(ctx: CheckContext) -> Iterable[Finding]:
    """Контраст текста к фону ниже порога своего класса.

    **Порог — по классу текста, правилом `designsystem.contrast`** (change
    `one-contrast-rule`). Один свод правил на страницу дизайн-системы, вёрстку и аудит:
    крупный текст (от 18 pt или от 14 pt полужирным) — 3,0, обычный — 4,5. Подпись
    берёт минимум своего кегля, а сверх него у неё есть комфортный порог слоя (7,0).
    Подпись между минимумом и комфортом — находка `info`, а не ошибка: минимум взят,
    не хватает запаса. Иначе каждый шаблон с серой подписью давал бы ошибку на каждом
    слайде, как `font_not_in_theme` до C3.

    Фон берётся **макета**, а не темы. Разница не теоретическая: 19.09 колода из
    двенадцати заголовков цвета `dk1` на макете, залитом `dk1`, прошла аудит без единой
    находки — контраст 1:1 сравнивался со светлым слотом темы и выходил 21:1.

    Проверяются блоки, у которых цвет задан **явно**: это наш выбор, и отвечаем за него
    мы. Блок без `color_ref` наследует цвет плейсхолдера шаблона, и спрашивать за него
    с генератора нельзя — шаблон не нарушает сам себя (тот же довод, что у
    `self_positioned_blocks`). Свободный текст без `color_ref` цвет получает при записи
    тем же правилом слоя (`contrast.readable_ref`, класс обычного текста), поэтому
    неразличимым он становится только на шаблоне, где порог не берёт ни один слот.
    """
    manifest = ctx.manifest
    colors = manifest.theme.colors
    thresholds = contrast_thresholds(ctx)

    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        background, background_source = _background_of(layout, manifest)
        for block in slide.blocks:
            if not carries_text(block):
                continue
            ref = getattr(block, "color_ref", None)
            if not isinstance(ref, ColorRef):
                continue
            kind, role_kind = block_text_classes(block, manifest)
            required = thresholds[kind]
            # Запас слой даёт не каждому классу: у кого его нет, у того комфорт — это
            # минимум из конфига, и промежутка для `info` не остаётся.
            has_margin = comfort_ratio(role_kind) > required_ratio(role_kind)
            comfort = max(required, comfort_ratio(role_kind)) if has_margin else required

            foreground = colors.get(ref)
            ratio = contrast_ratio(foreground, background)
            if ratio >= comfort:
                continue
            evidence = {
                "foreground": foreground,
                "background": background,
                "background_source": background_source,
                "ratio": f"{ratio:.2f}",
                "text_class": role_kind.value,
                "minimum_class": kind.value,
                "required": f"{required:.1f}",
                "comfort": f"{comfort:.1f}",
            }
            if ratio >= required:
                # Минимум взят, запаса нет: замечание, а не нарушение.
                yield make_finding(
                    check_id="template.contrast_below_wcag",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=block_bbox(block, layout),
                    reason=f"contrast-tight:{ref.value}",
                    message=(
                        f"Контраст подписи блока {block.block_id} к фону {ratio:.1f}:1 — "
                        f"минимум {required:.1f}:1 взят, но без запаса {comfort:.1f}:1"
                    ),
                    evidence=evidence,
                    severity=Severity.INFO,
                )
                continue
            yield make_finding(
                check_id="template.contrast_below_wcag",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason=f"contrast:{ref.value}",
                message=(
                    f"Контраст текста блока {block.block_id} к фону {ratio:.1f}:1 "
                    f"при требуемых {required:.1f}:1"
                ),
                evidence=evidence,
            )


def _background_of(layout: LayoutSpec | None, manifest: TemplateManifest) -> tuple[str, str]:
    """Фон, по которому читается текст слайда, и честное объяснение, откуда он взят.

    Манифест, снятый парсером до change (24), фона не описывает. Подставлять вместо него
    светлый слот темы молча нельзя — именно это и дало ложное «нарушений нет», — поэтому
    источник едет в `evidence` каждой находки.
    """
    background = layout.background if layout is not None else None
    if background is None:
        return (
            manifest.theme.colors.get(ColorRef.LT1),
            "тема lt1: манифест снят парсером без разбора фона",
        )
    if background.is_image:
        return (
            background.color_hex,
            f"{background.source}: усреднённый цвет подложки, вердикт приблизителен",
        )
    return background.color_hex, background.source
