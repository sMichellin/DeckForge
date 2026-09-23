"""Три стиля списка по дизайн-системе. Change `compose-by-the-design-system` (DG3).

Стиль выбирает композиция (`BulletsBlock.style`), рисует вёрстка — параметрами
дизайн-системы шаблона, своих чисел здесь нет:

* **маркированный** — маркер шаблона (`manifest.bullet_levels`, он же `bullets` ДС), как было;
* **нумерованный** — автонумерация PowerPoint с тем же выносом, что у маркера шаблона;
  цвет номера — акцент по роли ДС, читаемый как текст (`DesignRules.number_ink`);
* **иконочный** — иконка набора проекта слева от каждого пункта. Сторона иконки — кегль
  текста (один em), отбивка до текста — шаг элемента `icon` ДС, не шире
  `MAX_INSET_SHARE` рамки. Текст — одна рамка справа от колонки иконок: он остаётся
  одним редактируемым списком, а иконки встают по первой строке своего пункта.

Иконочный список рисуется только **свободным** блоком: в плейсхолдере шаблона абзацы
верстает PowerPoint, и иконку к строке пункта там не привязать. Список с иконками
в плейсхолдере рисуется маркером шаблона.

Раскладка одна на вписывание, pptx и html — как у цитаты (`layout.boxed`).
"""

from __future__ import annotations

from dataclasses import dataclass

from deckforge.domain.base import BBox
from deckforge.domain.enums import ListStyle, TextRole
from deckforge.domain.slide import BulletsBlock
from deckforge.domain.template import TemplateManifest
from deckforge.domain.units import EMU_PER_PT, TEXT_FRAME_INSET_X_EMU, TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.metrics import line_height_emu, measure_text, usable_height_emu


def list_style(block: BulletsBlock) -> ListStyle:
    """Стиль, которым список будет нарисован. Не задан — маркированный, как было."""
    return block.style or ListStyle.BULLETED


def draws_icons(block: BulletsBlock) -> bool:
    """Рисуется ли список с иконками: стиль `icon` и своя рамка (свободный блок)."""
    return list_style(block) is ListStyle.ICON and block.bbox is not None


@dataclass(frozen=True)
class IconColumn:
    """Колонка иконок слева: сторона иконки и отбивка текста от неё, в EMU."""

    side_emu: int
    pad_emu: int

    @property
    def width_emu(self) -> int:
        return self.side_emu + self.pad_emu


def icon_column(box: BBox, size_pt: float, rules: DesignRules) -> IconColumn:
    """Сторона иконки — один em кегля пункта, отбивка — шаг ДС по рамке блока."""
    return IconColumn(side_emu=round(size_pt * EMU_PER_PT), pad_emu=rules.icon_pad_emu(box.cx))


def icon_text_frame(box: BBox, column: IconColumn) -> BBox:
    """Рамка текста: рамка блока без колонки иконок слева."""
    shift = min(box.cx - 1, column.width_emu)
    return BBox(x=box.x + shift, y=box.y, cx=max(1, box.cx - shift), cy=box.cy)


@dataclass(frozen=True)
class IconListGeometry:
    #: Рамка текста справа от колонки иконок, во всю высоту блока.
    frame: BBox
    #: Иконка на пункт — по середине первой строки пункта.
    icons: list[BBox]


def icon_list_geometry(
    block: BulletsBlock,
    box: BBox,
    size_pt: float,
    manifest: TemplateManifest,
    rules: DesignRules,
    *,
    fonts: FontLibrary | None = None,
) -> IconListGeometry:
    """Где встанут иконки: текст по середине рамки (как у свободного текста), пункты
    друг под другом, иконка — по середине первой строки своего пункта.

    Высоты пунктов меряются тем же `measure_text`, что и вписывание: иначе иконка
    разошлась бы со строкой, к которой она относится."""
    step = manifest.typography(block.role) or manifest.typography(TextRole.BODY)
    theme_fonts = manifest.theme.fonts
    font_family = (theme_fonts.get(step.font_ref) if step else None) or theme_fonts.minor_latin
    line_spacing = (step.line_spacing if step else None) or 1.0
    column = icon_column(box, size_pt, rules)
    frame = icon_text_frame(box, column)
    line = round(line_height_emu(size_pt, line_spacing))
    heights = [
        measure_text(
            item.text, font_family=font_family, size_pt=size_pt, box=frame,
            line_spacing=line_spacing, bold=bool(step and step.bold),
            italic=bool(step and step.italic), fonts=fonts,
        ).height_emu
        or line
        for item in block.items
    ]
    top = box.y + TEXT_FRAME_INSET_Y_EMU + max(0, (usable_height_emu(box) - sum(heights)) // 2)
    side = min(column.side_emu, line, box.cx)
    icons: list[BBox] = []
    for height in heights:
        icons.append(
            BBox(
                x=box.x + min(TEXT_FRAME_INSET_X_EMU, max(0, box.cx - side)),
                y=top + max(0, (line - side) // 2),
                cx=max(1, side),
                cy=max(1, side),
            )
        )
        top += height
    return IconListGeometry(frame=frame, icons=icons)
