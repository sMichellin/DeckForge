"""Авто-кегль и стратегия вписывания. Change (12) `layout-fitting`.

Порядок деградации (из METHOD прежнего проекта, переписано без брендовых констант):
1. как есть → 2. ступень кегля вниз по шкале шаблона → 3. сокращение текста LLM →
4. деление слайда надвое. Заголовок не уменьшается никогда.

Слой `layout` LLM не вызывает (ARCHITECTURE.md §3): шаги 3 и 4 он **назначает** в
`FitResult.strategy`, а выполняют их композиция и граф. Главное — переполнение видно
в `SlideIR.fit_report` до того, как рендерер создаст файл.
"""

from __future__ import annotations

from deckforge.domain.base import BBox
from deckforge.domain.enums import TextRole
from deckforge.domain.rules import next_size_down
from deckforge.domain.slide import BulletsBlock, FitResult, SlideIR, TextBlock
from deckforge.domain.template import LayoutSpec, TemplateManifest, TypographyStep
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.metrics import measure_text, split_paragraphs, usable_height_emu

#: Во сколько раз текст может не влезать, чтобы его ещё имело смысл сокращать, а не делить
#: слайд. 1,5 — срезать до трети: больше LLM теряет смысл, а не воду. Это политика
#: вёрстки, а не свойство шаблона.
SHORTEN_MAX_OVERFLOW = 1.5

AS_IS = "as_is"
SHRINK = "shrink"
SHORTEN = "shorten"
SPLIT = "split"


class LayoutFitError(ValueError):
    """IR нельзя вписать: макета или плейсхолдера нет, места под блоки не осталось."""


def fit_text(
    text: str,
    *,
    box: BBox,
    manifest: TemplateManifest,
    start_size_pt: float,
    font_family: str,
    allow_shrink: bool = True,
    bold: bool = False,
    italic: bool = False,
    line_spacing: float = 1.0,
    fonts: FontLibrary | None = None,
) -> FitResult:
    """Подбирает кегль по шкале шаблона; не влезло на нижней ступени — назначает стратегию."""
    available = usable_height_emu(box)
    ladder = manifest.size_ladder_pt
    size = start_size_pt
    if ladder and size not in ladder:
        # Кегль вне шкалы шаблона не используется даже как стартовый (ADR-002).
        size = next_size_down(manifest, size) or min(ladder)
    while True:
        m = measure_text(
            text, font_family=font_family, size_pt=size, box=box,
            line_spacing=line_spacing, bold=bold, italic=italic, fonts=fonts,
        )
        if m.height_emu <= available:
            return FitResult(
                final_size_pt=size,
                overflow=False,
                lines=m.lines,
                required_cy_emu=m.height_emu,
                strategy=AS_IS if size == start_size_pt else SHRINK,
            )
        smaller = next_size_down(manifest, size) if allow_shrink else None
        if smaller is None:
            break
        size = smaller

    ratio = m.height_emu / available if available else float("inf")
    splittable = allow_shrink and len(split_paragraphs(text)) > 1
    return FitResult(
        final_size_pt=size,
        overflow=True,
        lines=m.lines,
        required_cy_emu=m.height_emu,
        strategy=SPLIT if splittable and ratio > SHORTEN_MAX_OVERFLOW else SHORTEN,
    )


def _step_for(role: TextRole, manifest: TemplateManifest) -> TypographyStep:
    step = manifest.typography(role) or manifest.typography(TextRole.BODY)
    if step is None:
        raise LayoutFitError(f"в типошкале шаблона нет ни роли {role}, ни основного текста")
    return step


def _box_for(block: TextBlock | BulletsBlock, layout: LayoutSpec) -> BBox:
    if block.bbox is not None:
        return block.bbox
    if block.placeholder_idx is None:
        raise LayoutFitError(f"блок {block.block_id}: нет ни координат, ни плейсхолдера")
    placeholder = layout.placeholder(block.placeholder_idx)
    if placeholder is None:
        raise LayoutFitError(
            f"блок {block.block_id}: в макете {layout.layout_id} нет плейсхолдера "
            f"idx={block.placeholder_idx}"
        )
    return placeholder.bbox


def fit_block(
    block: TextBlock | BulletsBlock,
    layout: LayoutSpec,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
) -> FitResult:
    """Вписывает текстовый блок: кегль и гарнитура — из типошкалы его роли."""
    step = _step_for(block.role, manifest)
    font = manifest.theme.fonts.get(step.font_ref) or manifest.theme.fonts.minor_latin
    text = block.text if isinstance(block, TextBlock) else "\n".join(i.text for i in block.items)
    return fit_text(
        text,
        box=_box_for(block, layout),
        manifest=manifest,
        start_size_pt=block.size_pt or step.size_pt,
        font_family=font,
        allow_shrink=block.role is not TextRole.TITLE,
        bold=step.bold,
        italic=step.italic,
        line_spacing=step.line_spacing or 1.0,
        fonts=fonts,
    )


def fit_slide(
    slide: SlideIR, manifest: TemplateManifest, *, fonts: FontLibrary | None = None
) -> SlideIR:
    """Возвращает слайд с заполненным `fit_report` по всем текстовым блокам."""
    layout = manifest.layout(slide.layout_id)
    if layout is None:
        raise LayoutFitError(f"слайд {slide.slide_id}: макета {slide.layout_id} нет в манифесте")
    report = {
        block.block_id: fit_block(block, layout, manifest, fonts=fonts)
        for block in slide.blocks
        if isinstance(block, TextBlock | BulletsBlock)
    }
    return slide.model_copy(update={"fit_report": report})
