"""Единицы измерения OOXML.

Это **единственный** модуль, где разрешены числовые литералы, связанные с геометрией
(ARCHITECTURE.md §13, гейт `lint_no_template_constants`). Всё остальное в `src/` получает
размеры только из `TemplateManifest`.
"""

from __future__ import annotations

from typing import Final, NewType

Emu = NewType("Emu", int)
"""English Metric Unit — базовая единица OOXML."""

EMU_PER_INCH: Final[int] = 914_400
EMU_PER_CM: Final[int] = 360_000
EMU_PER_PT: Final[int] = 12_700
EMU_PER_PX_96DPI: Final[int] = 9_525


#: Внутренние поля текстового фрейма PowerPoint по умолчанию: 0.1" по бокам, 0.05" сверху.
#: Это константы формата, а не конкретного шаблона, поэтому им место здесь.
TEXT_FRAME_INSET_X_EMU: Final[int] = EMU_PER_INCH // 10
TEXT_FRAME_INSET_Y_EMU: Final[int] = EMU_PER_INCH // 20

#: Направляющие в viewProps задаются в 1/8 точки.
EMU_PER_GUIDE_UNIT: Final[float] = EMU_PER_PT / 8


def pt_to_emu(pt: float) -> Emu:
    return Emu(round(pt * EMU_PER_PT))


def emu_to_pt(emu: int) -> float:
    return emu / EMU_PER_PT


def cm_to_emu(cm: float) -> Emu:
    return Emu(round(cm * EMU_PER_CM))


def emu_to_cm(emu: int) -> float:
    return emu / EMU_PER_CM


def inch_to_emu(inch: float) -> Emu:
    return Emu(round(inch * EMU_PER_INCH))


def px_to_emu(px: float, dpi: int = 96) -> Emu:
    return Emu(round(px * EMU_PER_INCH / dpi))


def emu_to_px(emu: int, dpi: int = 96) -> float:
    return emu * dpi / EMU_PER_INCH
