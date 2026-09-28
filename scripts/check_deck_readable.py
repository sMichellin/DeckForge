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
* кегль ниже читаемого;
* два текста наезжают друг на друга (RG39);
* на слайде осталась пустая рамка **от нашего текста** (RG40).

Последние две добавлены 26.09, и обе — оттого, что на слайды вернулось содержание
(RG28). Пока слайд был пуст, наезжать было нечему и пустая карточка терялась среди
пустого слайда. Оба дефекта нашлись глазами на превью, то есть ровно тем способом,
который этот замер и должен заменять.

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
from deckforge.layout.metrics import LINE_HEIGHT_RATIO, measure_text

#: Кегль, ниже которого текст на слайде перестаёт читаться с расстояния. Порог приёмки,
#: а не правило формата: поток B на приёмке RG29 получил тело на 7,8 pt — вписывание,
#: доведённое до нечитаемости, меняет один брак на другой.
DEFAULT_SIZE_FLOOR_PT = 10.0

#: Вид находки «кегль ниже порога»: по нему строку 7 сводит мерило плана Б.
BELOW_FLOOR = "кегль ниже порога"

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
    #: Фигуры, не попавшие в проверку наложения: кегль унаследован, текст не померить.
    unmeasured_place: int = 0
    #: Пустые рамки, пустые и в самом шаблоне: композиция автора, а не наш брак.
    blank_in_template: int = 0
    #: Фигуры за краем слайда, которые за краем и в шаблоне: вылет автора, а не наш.
    outside_in_template: int = 0
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


#: Вылет фигуры за край слайда с каждой стороны, EMU: слева, сверху, справа, снизу.
Overhang = tuple[int, int, int, int]
#: Слова для сторон вылета — в том же порядке, что `Overhang`.
_SIDES = ("слева", "сверху", "справа", "снизу")


def _overhang(shape: object, slide_cx: int, slide_cy: int) -> Overhang | None:
    """Вылет фигуры за край с каждой стороны. `None` — рамка неизвестна."""
    box = [getattr(shape, name, None) for name in ("left", "top", "width", "height")]
    if any(value is None for value in box):
        return None
    left, top, width, height = (int(value) for value in box)  # type: ignore[arg-type]
    return (
        max(0, -left),
        max(0, -top),
        max(0, left + width - slide_cx),
        max(0, top + height - slide_cy),
    )


def _says_overhang(over: Overhang) -> str:
    """Вылет словами: только те стороны, где он есть."""
    sides = zip(_SIDES, over, strict=True)
    return ", ".join(f"{side} на {value}" for side, value in sides if value)


def _outside(shape: object, slide_cx: int, slide_cy: int) -> str | None:
    """Насколько фигура вышла за край слайда. `None` — не вышла или рамка неизвестна."""
    over = _overhang(shape, slide_cx, slide_cy)
    if over is None:
        return None
    return _says_overhang(over) or None


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


def _has_frame(shape: object) -> bool:
    """Рамка фигуры известна целиком и не пуста."""
    box = [getattr(shape, name, None) for name in ("left", "top", "width", "height")]
    return not any(value is None for value in box) and int(box[2] or 0) > 0


def _text_height(
    shape: object, family: str | None, size_pt: float, library: FontLibrary
) -> int | None:
    """Высота текста в рамке этой ширины — столько места он занимает на самом деле."""
    width = int(getattr(shape, "width", 0) or 0)
    height = int(getattr(shape, "height", 0) or 0)
    if width <= 0:
        return None
    frame = BBox(x=0, y=0, cx=width, cy=max(height, 1))
    measured = measure_text(
        shape.text_frame.text,  # type: ignore[attr-defined]
        font_family=family or _UNNAMED_FAMILY,
        size_pt=size_pt,
        box=frame,
        bold=False,
        fonts=library,
    )
    return measured.height_emu + 2 * TEXT_FRAME_INSET_Y_EMU


def _occupied(shape: object, text_height: int | None) -> BBox | None:
    """Место, которое фигура занимает на слайде, — это её **текст**, а не рамка.

    Высота — высота текста: столько строк, сколько написано. Рамка выше текста места
    не занимает, и перекрытие самих рамок браком не является — рамки зон шаблона
    перекрываются у автора (у WorkSpace заголовок заходит на 349 055 EMU под зону тела),
    и ему это не мешало: его текст короче рамки. Прежняя формула брала большее из двух
    и обвиняла шаблон в наложении, которого на слайде нет (RG47).

    Ширина остаётся от рамки: по горизонтали текст занимает её всю — перенос идёт
    по ширине рамки.

    Текст, который в рамку не влез, ловит своя проверка «текст выше рамки»: он рисуется
    за нижним краем, и это находка сама по себе, а не через наложение.
    """
    box = [getattr(shape, name, None) for name in ("left", "top", "width", "height")]
    if any(value is None for value in box):
        return None
    left, top, width, height = (int(value) for value in box)  # type: ignore[arg-type]
    if width <= 0 or height <= 0 or not text_height:
        return None
    return BBox(x=left, y=top, cx=width, cy=text_height)


def _overlap(first: BBox, second: BBox) -> tuple[int, int]:
    """Пересечение двух мест по ширине и высоте, в EMU. Ноль — не пересекаются."""
    wide = min(first.x + first.cx, second.x + second.cx) - max(first.x, second.x)
    high = min(first.y + first.cy, second.y + second.cy) - max(first.y, second.y)
    return max(0, wide), max(0, high)


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


def filled_in_template(template: Path | None) -> set[str]:
    """Имена фигур шаблона, в которых **есть** текст автора.

    Нужны, чтобы не обвинять шаблон в своих мерках. Пустая рамка на готовом слайде
    значит одно из двух: автор оставил её пустой под заполнение (у VK Tech в примере 18
    таких рамок девятнадцать, у WorkSpace в примере 29 — две) или текст в ней был
    и стёрли его мы. Брак — только второе, и отличить их можно лишь по шаблону.

    Ключ — имя фигуры: писатель копирует её вместе с именем, и оно переживает запись.
    """
    if template is None:
        return set()
    return {
        str(shape.name)
        for slide in Presentation(str(template)).slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
    }


def outside_in_template(template: Path | None) -> dict[str, Overhang]:
    """Вылеты фигур шаблона за край его слайда: имя фигуры → вылет с каждой стороны.

    Нужны, чтобы не обвинять шаблон в своих мерках — тем же приёмом, которым
    `filled_in_template` отличает пустую рамку автора от стёртой нами. Прогон `96ef159`
    дал единственную находку края на фигуре, которая выходит за край и в слайде-примере
    шаблона, и ровно на столько же: писатель копирует пример целиком и фигур не двигает.

    Ключ — имя фигуры: оно копируется вместе с фигурой и переживает запись.
    """
    if template is None:
        return {}
    presentation = Presentation(str(template))
    slide_cx = int(presentation.slide_width or 0)
    slide_cy = int(presentation.slide_height or 0)
    outside: dict[str, Overhang] = {}
    for slide in presentation.slides:
        for shape in slide.shapes:
            over = _overhang(shape, slide_cx, slide_cy)
            if over is None or not any(over):
                continue
            name = str(getattr(shape, "name", "?"))
            known = outside.get(name)
            outside[name] = over if known is None else tuple(map(max, known, over))  # type: ignore[assignment]
    return outside


def check_deck(
    path: Path,
    *,
    size_floor_pt: float,
    library: FontLibrary,
    filled: set[str] | None = None,
    outside: dict[str, Overhang] | None = None,
) -> DeckReport:
    """Замер одной колоды. Ничего не пишет и файла не трогает."""
    presentation = Presentation(str(path))
    slide_cx = int(presentation.slide_width or 0)
    slide_cy = int(presentation.slide_height or 0)
    report = DeckReport(path=path)

    for number, slide in enumerate(presentation.slides, start=1):
        report.slides += 1
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            report.notes += 1
        #: Место каждого текста слайда — для проверки на наложение (RG39).
        taken: list[tuple[str, BBox, float]] = []
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            if not shape.text_frame.text.strip():
                # Пустая рамка (RG40). Находка — только там, где текст в шаблоне был:
                # значит, стёрли его мы. Пустая у автора рамка остаётся справкой:
                # это его композиция, и удалять её — не наше дело (RG36).
                if not _has_frame(shape):
                    continue
                name = str(getattr(shape, "name", "?"))
                if filled and name in filled:
                    report.findings.append(
                        Finding(
                            number, name, "пустая рамка",
                            "текст автора стёрт, а нашего не встало",
                        )
                    )
                else:
                    report.blank_in_template += 1
                continue
            name = str(getattr(shape, "name", "?"))
            if shape.left is not None:
                report.left_edges[int(shape.left)] += 1

            over = _overhang(shape, slide_cx, slide_cy)
            if over is not None and any(over):
                # Вылет автора — не наш брак (RG58). Находка — только вылет больше
                # шаблонного хотя бы с одной стороны: значит, фигуру отодвинули мы.
                author = (outside or {}).get(name)
                theirs = zip(over, author, strict=True) if author is not None else ()
                if author is not None and all(ours <= his for ours, his in theirs):
                    report.outside_in_template += 1
                else:
                    report.findings.append(
                        Finding(
                            number, name, "за краем слайда",
                            f"фигура вышла {_says_overhang(over)} EMU",
                        )
                    )

            usable = _usable_width(shape)
            runs = _runs(shape)
            known = next((size for _, size, _, _ in runs if size is not None), None)
            family = next((fam for _, size, fam, _ in runs if size is not None), None)
            # Место под наложение считается только у фигуры с известным кеглем: у чужой
            # рамки текст не померить, а перекрытие самих рамок — не брак. Рамки зон
            # в шаблонах перекрываются сплошь и рядом (у WorkSpace заголовок заходит
            # на 349 055 EMU под зону тела), и автору это не мешало: его текст короче
            # рамки. Судить надо по тексту, иначе замер обвиняет шаблон.
            if known is None:
                report.unmeasured_place += 1
            else:
                place = _occupied(shape, _text_height(shape, family, known, library))
                if place is not None:
                    taken.append((name, place, known))
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
                            BELOW_FLOOR,
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
        report.findings.extend(_collisions(number, taken))
    return report


def _collisions(number: int, taken: list[tuple[str, BBox, float]]) -> list[Finding]:
    """Пары текстов, наезжающих друг на друга больше, чем на половину строки (RG39).

    Порог — половина строки меньшего из двух кеглей: пара рамок может соприкасаться
    краями законно, но перекрытие в полстроки означает, что буквы легли на буквы.
    Считается по месту **с текстом**, а не по рамке: заголовок, не влезший в свою
    зону, рисуется ниже её края и накрывает тело слайда — на превью WorkSpace s05
    ровно это и видно.
    """
    found: list[Finding] = []
    for index, (name, place, size) in enumerate(taken):
        for other_name, other, other_size in taken[index + 1 :]:
            wide, high = _overlap(place, other)
            if not wide or not high:
                continue
            line = min(size, other_size) * LINE_HEIGHT_RATIO * EMU_PER_PT
            if high <= line / 2:
                continue
            found.append(
                Finding(
                    number,
                    f"{name} × {other_name}",
                    "тексты наложились",
                    f"перекрытие {wide}×{high} EMU при строке {round(line)} EMU",
                )
            )
    return found


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
    if report.blank_in_template:
        print(
            f"  пустых рамок автора: {report.blank_in_template} — пусты и в шаблоне, "
            "это его композиция"
        )
    if report.outside_in_template:
        print(
            f"  фигур за краем шаблона: {report.outside_in_template} — вылезают и в нём, "
            "это композиция автора"
        )
    if report.unmeasured_place:
        print(
            f"  вне проверки наложения: {report.unmeasured_place} фигур — "
            "кегль унаследован, высоту текста не померить"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("decks", nargs="+", type=Path, help="готовые .pptx")
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="шаблон, из которого собрана колода: без него пустые рамки нельзя "
        "отличить от пустых рамок автора, и они уходят в справку",
    )
    parser.add_argument(
        "--size-floor-pt",
        type=float,
        default=DEFAULT_SIZE_FLOOR_PT,
        help="кегль, ниже которого текст считается нечитаемым "
        f"(по умолчанию {DEFAULT_SIZE_FLOOR_PT:g})",
    )
    args = parser.parse_args(argv)

    library = _library()
    filled = filled_in_template(args.template)
    outside = outside_in_template(args.template)
    total = 0
    for path in args.decks:
        report = check_deck(
            path,
            size_floor_pt=args.size_floor_pt,
            library=library,
            filled=filled,
            outside=outside,
        )
        _print(report)
        total += len(report.findings)

    print(f"\nВсего находок: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
