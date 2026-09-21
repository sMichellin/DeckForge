"""Метрики оформления по отрисованному слайду. Change (15) `audit-deterministic`.

Геометрия IR отвечает на вопрос «где стоят рамки», но не на вопрос «как слайд выглядит».
Прогон `5f20ce07e504`: показатели набраны 36-м кеглем и стоят по центру, а проверка
`density.fill_ratio` считает слайд полупустым — потому что «чернил» в нём две строки.
Мерить плакат по площади букв бессмысленно.

Поэтому здесь метрики считаются по картинке слайда — так же, как это делают работы
по оценке слайдов (arXiv:2508.19289: «whitespace, text density, edge density, layout
balance… lightweight image processing operators, for example pixel intensity thresholds,
Canny edges»). Это ровно то, что архитектурный обзор называет CV-анализом рендера.

Две величины, обе безразмерные:

* **чернила** — доля пикселей-границ. Текст и фигуры дают границы, ровный фон
  и градиент шаблона — нет, поэтому метрика не путает тёмный фон с содержанием;
* **смещение центра** — насколько центр тяжести чернил ушёл от центра слайда.

Ни та, ни другая сама по себе не «хорошая» и не «плохая»: порог здесь — это про край,
а не про вкус. Смещение ловит именно тот дефект, которого не видела геометрия: содержание,
прижатое к верхнему краю, при формально заполненных рамках (прогон 693d464d54fb —
8 слайдов из 10 со смещением 0,29–0,44 против 0,04–0,20 после центрирования).
"""

from __future__ import annotations

import io
from collections.abc import Iterable

from PIL import Image, ImageChops, ImageFilter

from deckforge.audit.findings import make_finding
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import Severity

#: Ширина, до которой ужимается превью перед счётом. Метрика не о деталях, а о массе:
#: на 320 точках она устойчива к кеглю и считается за миллисекунды.
_WIDTH = 320

#: Яркость границы, начиная с которой пиксель считается чернилами.
_EDGE = 32

#: Радиус окна локальной дисперсии в точках ужатого превью. У AeSlides (arXiv:2604.22840)
#: окно 201×151 при ширине 1280 — шестая часть ширины; здесь столько же в долях.
_VARIANCE_RADIUS = 18

#: Ниже этой доли от наибольшей локальной дисперсии место считается пустым — порог τ
#: той же работы.
_EMPTY_TAU = 0.05

#: Строка превью пуста, если пуста такая её доля: декор у края не делает строку занятой.
_EMPTY_ROW = 0.9


def ink_metrics(png: bytes) -> tuple[float, float]:
    """(доля чернил, смещение центра тяжести) по изображению слайда.

    Смещение — наибольшее отклонение центра тяжести по осям, приведённое к единице:
    0 — ровно в центре слайда, 1 — у самого края.
    """
    image = Image.open(io.BytesIO(png)).convert("L")
    height = max(1, round(_WIDTH * image.height / image.width))
    edges = image.resize((_WIDTH, height)).filter(ImageFilter.FIND_EDGES)

    # `get_flattened_data` — имя в Pillow 11+, `getdata` — в прежних. Список нужен
    # дважды: сначала на сумму, потом на центр тяжести.
    flatten = getattr(edges, "get_flattened_data", None) or edges.getdata
    mask = [1 if value > _EDGE else 0 for value in list(flatten())]
    total = sum(mask)
    if not total:
        return 0.0, 0.0

    width, height = edges.size
    x = sum((i % width) * m for i, m in enumerate(mask)) / total / width
    y = sum((i // width) * m for i, m in enumerate(mask)) / total / height
    return total / (width * height), max(abs(x - 0.5), abs(y - 0.5)) * 2


def empty_band(png: bytes) -> float:
    """Высота самой большой сплошной пустой полосы — доля высоты слайда.

    Пустота ищется по карте локальной дисперсии, как «excessive whitespace» у AeSlides
    (arXiv:2604.22840): место, где яркость почти не меняется, пусто — будь то ровный
    фон или плавный градиент шаблона. Считается не доля пустоты вообще, а самая большая
    сплошная полоса: пустота, разлитая между блоками, — это воздух, а одна большая
    дыра под текстом — недописанный слайд.
    """
    image = Image.open(io.BytesIO(png)).convert("L")
    height = max(1, round(_WIDTH * image.height / image.width))
    small = image.resize((_WIDTH, height))
    mean = small.filter(ImageFilter.BoxBlur(_VARIANCE_RADIUS))
    mean_sq = ImageChops.multiply(small, small).filter(ImageFilter.BoxBlur(_VARIANCE_RADIUS))

    flatten = getattr(mean, "get_flattened_data", None) or mean.getdata
    flatten_sq = getattr(mean_sq, "get_flattened_data", None) or mean_sq.getdata
    # multiply делит на 255: E[x²] приходит в тех же единицах, что E[x], делённое на 255.
    variance = [
        max(0.0, sq * 255 - m * m)
        for m, sq in zip(list(flatten()), list(flatten_sq()), strict=True)
    ]
    peak = max(variance) or 1.0

    width = _WIDTH
    run = best = 0
    for y in range(height):
        row = variance[y * width:(y + 1) * width]
        empty = sum(1 for value in row if value / peak < _EMPTY_TAU) / width
        run = run + 1 if empty > _EMPTY_ROW else 0
        best = max(best, run)
    return best / height


@check(id="design.ink_balance", deterministic=True, severity=Severity.WARNING,
       title="Содержание слайда прижато к краю или слайд перегружен")
def ink_balance(ctx: CheckContext) -> Iterable[Finding]:
    """Содержание слайда прижато к краю или слайд перегружен."""
    previews = ctx.previews
    if not previews:
        raise CheckUnavailable("превью слайдов нет: считать метрики оформления не по чему")

    max_offset = ctx.param("max_offset", 0.3)
    max_band = ctx.param("max_empty_band", 0.3)
    band_offset = ctx.param("band_needs_offset", 0.15)
    min_ink = ctx.param("min_ink", 0.005)
    max_ink = ctx.param("max_ink", 0.15)

    for slide in ctx.deck.slides:
        png = previews.get(slide.slide_id)
        if png is None:
            continue
        ink, offset = ink_metrics(png)

        if ink < min_ink:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="ink:empty",
                message=f"Слайд почти пуст: содержание занимает {ink:.1%} площади",
                evidence={"ink": f"{ink:.4f}", "offset": f"{offset:.2f}"},
            )
            continue
        if ink > max_ink:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="ink:crowded",
                message=f"Слайд перегружен: содержание занимает {ink:.1%} площади",
                evidence={"ink": f"{ink:.4f}", "offset": f"{offset:.2f}"},
            )
            continue
        # Пустые полосы над и под рядом показателей по центру — это воздух, и так
        # задумано; дефект — пустота с одной стороны от содержания. Поэтому полоса
        # засчитывается, только когда центр тяжести заметно ушёл: пустота и дисбаланс
        # вместе, как их и складывает AeSlides.
        band = empty_band(png)
        if band > max_band and offset > band_offset:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="whitespace:band",
                message=(
                    f"На слайде пустая полоса в {band:.0%} высоты при допустимых "
                    f"{max_band:.0%}: содержание не заняло отведённого"
                ),
                evidence={"ink": f"{ink:.4f}", "offset": f"{offset:.2f}", "band": f"{band:.2f}"},
            )
            continue
        if offset > max_offset:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="balance:off_centre",
                message=(
                    f"Содержание прижато к краю: центр тяжести смещён на {offset:.2f} "
                    f"при допустимых {max_offset:.2f}"
                ),
                evidence={"ink": f"{ink:.4f}", "offset": f"{offset:.2f}"},
            )
