#!/usr/bin/env python3
"""Читаемость готовой колоды: то, что считается по файлу, а не ищется глазами.

Приёмка итерации 25.09 задана так: «превью каждого слайда глазами, ни одного
разорванного посередине слова и ни одного текста за краем слайда». Критерий верный,
способ негодный: четыре колоды по десять слайдов — сорок картинок на каждый прогон,
и смотреть их надо после каждого PR критического пути.

Так мы уже промахнулись. Три прогона 24.09 отчитались `done` с 13–26 находками аудита,
и ни одна находка не сказала главного: колоды нечитаемы. Увидеть это удалось, только
открыв превью руками.

Здесь считается то, что видно в самом файле, без IR, чекпойнта и шаблона:

* фигура вылезла за край слайда;
* текст не помещается в свою рамку по высоте;
* самое длинное слово шире своей рамки;
* кегль ниже читаемого.

**Разрыв слова в XML не виден** — там слово целое, рвёт его рендер. Но предпосылка
разрыва видна точно: слово, которое на своём кегле шире рамки, PowerPoint разорвёт
всегда. То же условие вёрстка проверяет изнутри (`TextMetrics`); здесь оно считается
по **готовому файлу**, то есть проверяет результат, а не намерение: вписывание могло
отработать и всё равно не спасти, если кегль поставил писатель.

Замер не заменяет глаза: композицию, цвет и осмысленность текста он не видит.
Он снимает с человека те находки, которые машина ищет быстрее и точнее.

    python scripts/check_deck_readable.py out/deck.pptx …
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from deckforge.domain.base import BBox
from deckforge.domain.units import EMU_PER_PT, TEXT_FRAME_INSET_X_EMU, TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.fonts import FontLibrary, FontMetrics
from deckforge.layout.metrics import measure_text

#: Кегль, ниже которого текст на слайде перестаёт читаться с расстояния. Порог приёмки,
#: а не правило формата: поток B на приёмке RG29 получил тело на 7,8 pt — вписывание,
#: доведённое до нечитаемости, меняет один брак на другой.
DEFAULT_SIZE_FLOOR_PT = 10.0

#: Гарнитура, которой считаем, когда шрифт фигуры в файле не назван. Имя ни к чему
#: не привязывает: `FontLibrary` всё равно отдаст замену и пометит замер неточным.
_UNNAMED_FAMILY = "Arial"


@dataclass(frozen=True, slots=True)
class Finding:
    """Находка замера. `slide` — номер по порядку в файле, с единицы."""

    slide: int
    shape: str
    kind: str
    message: str


@dataclass
class DeckReport:
    """Итог по одной колоде. Справки отделены от находок: они не брак."""

    path: Path
    slides: int = 0
    findings: list[Finding] = None  # type: ignore[assignment]
    #: Фигуры, у которых кегль унаследован от макета и из слайда не виден.
    unmeasured: int = 0
    #: Фигуры, посчитанные пессимистичной заменой шрифта.
    inexact_font: int = 0
    left_edges: Counter[int] = None  # type: ignore[assignment]
    notes: int = 0

    def __post_init__(self) -> None:
        if self.findings is None:
            self.findings = []
        if self.left_edges is None:
            self.left_edges = Counter()


def _library() -> FontLibrary:
    return FontLibrary.default()


def _metrics(library: FontLibrary, family: str, *, bold: bool) -> tuple[FontMetrics, bool]:
    resolved = library.resolve(family, bold=bold)
    return library.metrics(resolved.face), resolved.exact


def _longest_word(text: str, metrics: FontMetrics, size_pt: float) -> tuple[str, int]:
    """Самое широкое слово текста и его ширина в EMU на этом кегле."""
    words = [word for word in text.split() if word]
    if not words:
        return "", 0
    widest = max(words, key=metrics.text_width_em)
    return widest, round(metrics.text_width_em(widest) * size_pt * EMU_PER_PT)


def _usable_width(shape: object) -> int:
    """Ширина рамки за вычетом полей текста. Поля берём у самой фигуры: файл знает их
    точнее константы, а константа остаётся на случай, когда фигура их не задала."""
    width = int(getattr(shape, "width", 0) or 0)
    frame = getattr(shape, "text_frame", None)
    left = getattr(frame, "margin_left", None)
    right = getattr(frame, "margin_right", None)
    inset_left = int(left) if left is not None else TEXT_FRAME_INSET_X_EMU
    inset_right = int(right) if right is not None else TEXT_FRAME_INSET_X_EMU
    return max(0, width - inset_left - inset_right)


def _outside(shape: object, slide_cx: int, slide_cy: int) -> str | None:
    """Насколько фигура вышла за край слайда. `None` — не вышла или рамка неизвестна."""
    box = [getattr(shape, name, None) for name in ("left", "top", "width", "height")]
    if any(value is None for value in box):
        return None
    left, top, width, height = (int(value) for value in box)  # type: ignore[arg-type]
    over = []
    if left < 0:
        over.append(f"слева на {-left}")
    if top < 0:
        over.append(f"сверху на {-top}")
    if left + width > slide_cx:
        over.append(f"справа на {left + width - slide_cx}")
    if top + height > slide_cy:
        over.append(f"снизу на {top + height - slide_cy}")
    return ", ".join(over) or None


def _too_tall(
    shape: object, text: str, family: str, size_pt: float, *, bold: bool, library: FontLibrary
) -> str | None:
    """Во сколько строк ляжет текст и влезут ли они в рамку по высоте.

    Считается тем же `measure_text`, которым меряет вёрстка: иначе замер приёмки
    расходился бы с замером, по которому колода собиралась, и спорить было бы не о чем.
    Рамка с неизвестными координатами пропускается — высоту не с чем сравнивать.
    """
    box = [getattr(shape, name, None) for name in ("left", "top", "width", "height")]
    if any(value is None for value in box) or int(box[2] or 0) <= 0 or int(box[3] or 0) <= 0:
        return None
    left, top, width, height = (int(value) for value in box)  # type: ignore[arg-type]
    frame = BBox(x=max(0, left), y=max(0, top), cx=width, cy=height)
    measured = measure_text(
        text, font_family=family, size_pt=size_pt, box=frame, bold=bold, fonts=library
    )
    usable = max(0, height - 2 * TEXT_FRAME_INSET_Y_EMU)
    if measured.height_emu <= usable:
        return None
    return (
        f"{measured.lines} строк на {size_pt:g} pt — {measured.height_emu} EMU "
        f"при рамке {usable} EMU"
    )


def _runs(shape: object) -> list[tuple[str, float | None, str | None, bool]]:
    """Прогоны текста фигуры: текст, кегль, гарнитура, полужирность.

    Кегль и гарнитура бывают унаследованы от макета — тогда `None`: из слайда их
    не видно, и догадываться о них нельзя. Такая фигура уходит в «не измерено».
    """
    frame = getattr(shape, "text_frame", None)
    if frame is None:
        return []
    found: list[tuple[str, float | None, str | None, bool]] = []
    for paragraph in frame.paragraphs:
        for run in paragraph.runs:
            if not run.text.strip():
                continue
            size = run.font.size or paragraph.font.size
            size_pt = float(Emu(int(size)).pt) if size is not None else None
            family = run.font.name or paragraph.font.name
            found.append((run.text, size_pt, family, bool(run.font.bold)))
    return found


def check_deck(path: Path, *, size_floor_pt: float, library: FontLibrary) -> DeckReport:
    """Замер одной колоды. Ничего не пишет и файла не трогает."""
    presentation = Presentation(str(path))
    slide_cx = int(presentation.slide_width or 0)
    slide_cy = int(presentation.slide_height or 0)
    report = DeckReport(path=path)

    for number, slide in enumerate(presentation.slides, start=1):
        report.slides += 1
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            report.notes += 1
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False) or not shape.text_frame.text.strip():
                continue
            name = str(getattr(shape, "name", "?"))
            if shape.left is not None:
                report.left_edges[int(shape.left)] += 1

            over = _outside(shape, slide_cx, slide_cy)
            if over is not None:
                report.findings.append(
                    Finding(number, name, "за краем слайда", f"фигура вышла {over} EMU")
                )

            usable = _usable_width(shape)
            runs = _runs(shape)
            first = next(
                ((size, family, bold) for _, size, family, bold in runs if size is not None),
                None,
            )
            if first is not None:
                lead_size, lead_family, lead_bold = first
                tall = _too_tall(
                    shape,
                    shape.text_frame.text,
                    lead_family or _UNNAMED_FAMILY,
                    lead_size,
                    bold=lead_bold,
                    library=library,
                )
                if tall is not None:
                    report.findings.append(
                        Finding(number, name, "текст выше рамки", tall)
                    )
            for text, size_pt, family, bold in runs:
                if size_pt is None:
                    report.unmeasured += 1
                    continue
                if size_pt < size_floor_pt:
                    report.findings.append(
                        Finding(
                            number,
                            name,
                            "кегль ниже порога",
                            f"{size_pt:g} pt при пороге {size_floor_pt:g} pt",
                        )
                    )
                metrics, exact = _metrics(library, family or _UNNAMED_FAMILY, bold=bold)
                # Замер по чужой гарнитуре — оценка, а не факт: у замены свои ширины,
                # и находка на считанные проценты может оказаться её погрешностью.
                # Молчать об этом нельзя, поэтому помета едет в самой находке.
                guess = "" if exact else " (замер по замене шрифта — проверьте глазами)"
                if not exact:
                    report.inexact_font += 1
                word, width = _longest_word(text, metrics, size_pt)
                if usable and width > usable:
                    report.findings.append(
                        Finding(
                            number,
                            name,
                            "слово шире рамки",
                            f"«{word}» на {size_pt:g} pt занимает {width} EMU "
                            f"при рамке {usable} EMU — рендер разорвёт его посередине{guess}",
                        )
                    )
    return report


def _print(report: DeckReport) -> None:
    print(f"\n### {report.path}  — слайдов {report.slides}")
    for finding in report.findings:
        print(f"  s{finding.slide:02d}  {finding.kind:<18} {finding.shape}: {finding.message}")
    if not report.findings:
        print("  находок нет")
    columns = len(report.left_edges)
    print(
        f"  справки: колонок {columns}"
        f" ({', '.join(str(edge) for edge, _ in report.left_edges.most_common(5))})"
        f"; заметок докладчика {report.notes} из {report.slides}"
    )
    if report.unmeasured:
        print(f"  не измерено: {report.unmeasured} прогонов — кегль унаследован от макета")
    if report.inexact_font:
        print(f"  считано заменой шрифта: {report.inexact_font} прогонов — гарнитуры нет в системе")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("decks", nargs="+", type=Path, help="готовые .pptx")
    parser.add_argument(
        "--size-floor-pt",
        type=float,
        default=DEFAULT_SIZE_FLOOR_PT,
        help="кегль, ниже которого текст считается нечитаемым "
        f"(по умолчанию {DEFAULT_SIZE_FLOOR_PT:g})",
    )
    args = parser.parse_args(argv)

    library = _library()
    total = 0
    for path in args.decks:
        report = check_deck(path, size_floor_pt=args.size_floor_pt, library=library)
        _print(report)
        total += len(report.findings)

    print(f"\nВсего находок: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
