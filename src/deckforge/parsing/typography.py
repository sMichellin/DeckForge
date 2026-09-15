"""Вывод типографической шкалы шаблона. Change (4) `theme-extraction`.

Шкала не берётся из `txStyles` мастера напрямую: в шаблонах, выгруженных из сторонних
редакторов, там лежит одинаковый кегль на всех девяти уровнях, а настоящие размеры стоят
на плейсхолдерах макетов. Поэтому шкала **выводится** из наблюдений: какие кегли фактически
встречаются у плейсхолдеров каждой роли, и какой из них для этой роли типичен.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from lxml import etree

from deckforge.domain.enums import ColorRef, FontRef, TextRole
from deckforge.domain.template import Theme, TypographyStep
from deckforge.parsing.ooxml.theme import nearest_color_ref

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"

#: Порядок ролей по убыванию кегля — используется для восстановления пропусков.
ROLE_ORDER: tuple[TextRole, ...] = (
    TextRole.TITLE,
    TextRole.SUBTITLE,
    TextRole.BODY,
    TextRole.CAPTION,
)

#: Во сколько раз роль мельче соседней сверху, если в шаблоне её вовсе не встретилось.
#: Это не «типовой размер шаблона», а шаг геометрической прогрессии — им заполняется
#: только дырка в наблюдениях, и `TemplateManifest` фиксирует такой шаг как производный.
_FALLBACK_RATIO = 0.65


@dataclass(frozen=True, slots=True)
class TypographyObservation:
    """Один факт: у плейсхолдера такой-то роли встретился такой-то кегль."""

    role: TextRole
    size_pt: float
    bold: bool | None = None
    color_hex: str | None = None


def collect_observations(part_xml: bytes, role_by_idx: dict[int, TextRole]) -> list[
    TypographyObservation
]:
    """Наблюдения по одной части: кегль, жирность и цвет первого уровня плейсхолдера."""
    root = etree.fromstring(part_xml)
    out: list[TypographyObservation] = []

    for shape in root.iter(f"{{{P}}}sp"):
        ph = shape.find(f".//{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
        if ph is None:
            continue
        role = role_by_idx.get(int(ph.get("idx") or 0))
        if role is None:
            continue

        for props in (
            shape.find(f".//{{{A}}}lvl1pPr/{{{A}}}defRPr"),
            shape.find(f".//{{{A}}}defRPr"),
            shape.find(f".//{{{A}}}rPr"),
        ):
            if props is None or not props.get("sz"):
                continue
            bold_attr = props.get("b")
            srgb = props.find(f"{{{A}}}solidFill/{{{A}}}srgbClr")
            out.append(
                TypographyObservation(
                    role=role,
                    size_pt=int(props.get("sz")) / 100,
                    bold=(bold_attr == "1") if bold_attr is not None else None,
                    color_hex=f"#{srgb.get('val').upper()}" if srgb is not None else None,
                )
            )
            break
    return out


def _representative(values: list[float]) -> float:
    """Типичный кегль роли: самый частый, при равенстве — больший.

    Среднее здесь не годится: один нестандартный макет сместил бы всю шкалу.
    """
    counts = Counter(values)
    top = max(counts.values())
    return max(size for size, count in counts.items() if count == top)


def _dominant_bold(values: list[bool | None]) -> bool:
    known = [v for v in values if v is not None]
    return bool(known) and sum(known) * 2 > len(known)


def _dominant_color(values: list[str | None], theme: Theme, default: ColorRef) -> ColorRef:
    known = [v for v in values if v]
    if not known:
        return default
    hex_color, _ = Counter(known).most_common(1)[0]
    ref, distance = nearest_color_ref(hex_color, theme.colors)
    # Цвет, далёкий от всей палитры, — признак ручной правки в шаблоне, а не роли в шкале.
    return ref if distance <= 40 else default


def derive_scale(observations: list[TypographyObservation], theme: Theme) -> list[TypographyStep]:
    """Собрать шкалу из наблюдений. Роли без наблюдений восстанавливаются от соседних."""
    by_role: dict[TextRole, list[TypographyObservation]] = {}
    for obs in observations:
        by_role.setdefault(obs.role, []).append(obs)

    sizes: dict[TextRole, float] = {
        role: _representative([o.size_pt for o in items]) for role, items in by_role.items()
    }
    if not sizes:
        raise ValueError("в шаблоне не найдено ни одного кегля: нечего класть в типошкалу")

    # Дырки в наблюдениях заполняются от ближайшей известной роли сверху, затем снизу.
    for position, role in enumerate(ROLE_ORDER):
        if role in sizes:
            continue
        above = next((r for r in reversed(ROLE_ORDER[:position]) if r in sizes), None)
        if above is not None:
            sizes[role] = round(sizes[above] * _FALLBACK_RATIO, 1)
            continue
        below = next((r for r in ROLE_ORDER[position + 1 :] if r in sizes), None)
        if below is not None:
            sizes[role] = round(sizes[below] / _FALLBACK_RATIO, 1)

    # Шкала обязана убывать: иначе `next_size_down` начнёт увеличивать текст.
    ordered: list[TypographyStep] = []
    previous: float | None = None
    for role in ROLE_ORDER:
        size = sizes[role]
        if previous is not None and size >= previous:
            size = round(previous * _FALLBACK_RATIO, 1)
        previous = size

        items = by_role.get(role, [])
        default_color = ColorRef.DK1 if role in (TextRole.TITLE, TextRole.BODY) else ColorRef.DK2
        ordered.append(
            TypographyStep(
                role=role,
                size_pt=size,
                font_ref=FontRef.MAJOR_LATIN if role is TextRole.TITLE else FontRef.MINOR_LATIN,
                bold=_dominant_bold([o.bold for o in items]),
                color_ref=_dominant_color([o.color_hex for o in items], theme, default_color),
            )
        )
    return ordered
