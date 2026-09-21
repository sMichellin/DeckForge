"""Метрики оформления по отрисованному слайду. Change (15) `audit-deterministic`.

Геометрия IR отвечает на вопрос «где стоят рамки», но не на вопрос «как слайд выглядит».
Прогон `5f20ce07e504`: показатели набраны 36-м кеглем и стоят по центру, а проверка
`density.fill_ratio` считает слайд полупустым — потому что «чернил» в нём две строки.
Мерить плакат по площади букв бессмысленно.

Поэтому здесь метрики считаются по картинке слайда — так же, как это делают работы
по оценке слайдов (arXiv:2508.19289: «whitespace, text density, edge density, layout
balance… lightweight image processing operators, for example pixel intensity thresholds,
Canny edges»). Это ровно то, что архитектурный обзор называет CV-анализом рендера.

Три величины, все безразмерные:

* **чернила** — доля пикселей-границ. Текст и фигуры дают границы, ровный фон
  и градиент шаблона — нет, поэтому метрика не путает тёмный фон с содержанием;
* **дисбаланс** — насколько центр тяжести чернил ушёл от центра слайда, в допусках
  по осям;
* **пустая зона** — наибольший прямоугольник, где яркость почти не меняется.

Задача C9: всё это считается **по содержанию, а не по картинке целиком**. Пустой макет
вычитается из превью слайда, и логотип, плашка и градиент шаблона перестают участвовать
в метриках. До C9 они участвовали, и на `1d0bc29cf23f` s03 это было видно прямо: левые
60 % слайда пусты, а центр тяжести 0,61 — его тянул вправо логотип шаблона. Никакой порог
такого не поймает, пока декор шаблона считается содержанием.

Ни одна из величин сама по себе не «хорошая» и не «плохая»: порог здесь — это про край,
а не про вкус.
"""

from __future__ import annotations

import io
import math
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


def _shrunk(png: bytes, size: tuple[int, int] | None = None) -> Image.Image:
    """Серое изображение в рабочем размере."""
    image = Image.open(io.BytesIO(png)).convert("L")
    if size is None:
        height = max(1, round(_WIDTH * image.height / image.width))
        size = (_WIDTH, height)
    return image.resize(size)


def content_only(png: bytes, chrome: bytes | None = None) -> Image.Image:
    """Слайд без того, что нарисовал шаблон. Задача C9.

    Пустой макет и слайд на нём отрисованы одним и тем же LibreOffice в одном
    разрешении, поэтому там, где шаблона не коснулись, разница равна нулю: логотип,
    плашка и градиент уходят в чёрный, остаётся то, что на слайде появилось от нас.

    Без превью макета возвращается сам слайд. Метрика тогда считает декор шаблона
    содержанием — так она и работала до C9 — и это честнее, чем подставить вместо
    макета догадку.
    """
    slide = _shrunk(png)
    if chrome is None:
        return slide
    return ImageChops.difference(slide, _shrunk(chrome, slide.size))


def ink_metrics(png: bytes, chrome: bytes | None = None) -> tuple[float, float, float]:
    """(доля чернил, смещение по горизонтали, смещение по вертикали).

    Смещения — отклонения центра тяжести чернил от центра слайда в долях стороны:
    0 — ровно в центре, 0,5 — у самого края.
    """
    edges = content_only(png, chrome).filter(ImageFilter.FIND_EDGES)

    # `get_flattened_data` — имя в Pillow 11+, `getdata` — в прежних. Список нужен
    # дважды: сначала на сумму, потом на центр тяжести.
    flatten = getattr(edges, "get_flattened_data", None) or edges.getdata
    mask = [1 if value > _EDGE else 0 for value in list(flatten())]
    total = sum(mask)
    if not total:
        return 0.0, 0.0, 0.0

    width, height = edges.size
    x = sum((i % width) * m for i, m in enumerate(mask)) / total / width
    y = sum((i // width) * m for i, m in enumerate(mask)) / total / height
    return total / (width * height), abs(x - 0.5), abs(y - 0.5)


def imbalance(dx: float, dy: float, x_tol: float, y_tol: float) -> float:
    """Дисбаланс в допусках: ≤ 1 — центр тяжести внутри эллипса AeSlides.

    Допуск по горизонтали строже (arXiv:2604.22840: x_tol = 0,05, y_tol = 0,15): колода
    читается сверху вниз, содержание под заголовком естественно смещено вниз, а перекос
    вбок — дефект. Прежде смещение мерилось одним числом по худшей оси, то есть квадратом
    с одинаковой стороной.

    Сами допуски приходят порогами из `configs/audit_checks.yaml`: 0,05 — число работы,
    не откалиброванное на наших прогонах, и втрое ужесточить проверку разом значит
    превратить предупреждение в шум.
    """
    if y_tol <= 0:
        return 0.0
    x_tol = x_tol or y_tol
    return math.hypot(dx / x_tol, dy / y_tol)


def _empty_mask(image: Image.Image) -> list[bool]:
    """Где яркость почти не меняется — карта локальной дисперсии AeSlides."""
    mean = image.filter(ImageFilter.BoxBlur(_VARIANCE_RADIUS))
    mean_sq = ImageChops.multiply(image, image).filter(ImageFilter.BoxBlur(_VARIANCE_RADIUS))

    flatten = getattr(mean, "get_flattened_data", None) or mean.getdata
    flatten_sq = getattr(mean_sq, "get_flattened_data", None) or mean_sq.getdata
    # multiply делит на 255: E[x²] приходит в тех же единицах, что E[x], делённое на 255.
    variance = [
        max(0.0, sq * 255 - m * m)
        for m, sq in zip(list(flatten()), list(flatten_sq()), strict=True)
    ]
    peak = max(variance) or 1.0
    return [value / peak < _EMPTY_TAU for value in variance]


def _largest_empty_rect(mask: list[bool], width: int, height: int) -> tuple[int, int]:
    """Наибольший по площади пустой прямоугольник: его ширина и высота в точках.

    Обычная задача о наибольшем прямоугольнике в двоичной матрице — гистограмма высот
    плюс стек, один проход по изображению. На 320 точках ширины это миллисекунды.
    """
    # Лишняя нулевая колонка справа закрывает стек в конце каждой строки.
    heights = [0] * (width + 1)
    best_area = 0
    best = (0, 0)
    for y in range(height):
        row = mask[y * width : (y + 1) * width]
        for x in range(width):
            heights[x] = heights[x] + 1 if row[x] else 0
        stack: list[int] = []
        for x in range(width + 1):
            while stack and heights[stack[-1]] >= heights[x]:
                top = stack.pop()
                left = stack[-1] + 1 if stack else 0
                area = (x - left) * heights[top]
                if area > best_area:
                    best_area, best = area, (x - left, heights[top])
            stack.append(x)
    return best


def empty_zone(png: bytes, chrome: bytes | None = None) -> tuple[float, float]:
    """Наибольшая пустая зона: её ширина и высота в долях слайда. Задача C9.

    Пустота ищется по карте локальной дисперсии, как «excessive whitespace» у AeSlides
    (arXiv:2604.22840), но **в двух измерениях**. Прежде считалась самая высокая пустая
    строка, и незанятая правая половина слайда в метрику не попадала вовсе: строка
    считалась занятой, хотя занята она была наполовину (`f0b9ff6f0a74` — правая половина
    на семи слайдах, `1d0bc29cf23f` — левые 60 %).

    Пустота, разлитая между блоками, — это воздух; дефект — одна большая зона рядом
    с содержанием, поэтому считается не доля пустоты вообще, а наибольший прямоугольник.
    """
    image = content_only(png, chrome)
    width, height = image.size
    cells_w, cells_h = _largest_empty_rect(_empty_mask(image), width, height)
    return cells_w / width, cells_h / height


def slide_metrics(
    previews: dict[str, bytes],
    layouts_by_slide: dict[str, str],
    layout_previews: dict[str, bytes] | None = None,
    x_tol: float = 0.1,
    y_tol: float = 0.15,
) -> dict[str, dict[str, float]]:
    """Метрики оформления по каждому слайду, а не только по нарушителям. Задача C7.

    Находка появляется у слайда за порогом, и по находкам нельзя сказать, стала колода
    лучше или просто не дошла до порога. Сравнивать колоды между прогонами можно только
    по величинам, которые есть у каждого слайда, — их и кладёт в отчёт прогона
    `pipeline/run.py`, а `scripts/run_metrics.py` считает по ним медиану и разброс.
    """
    chrome_by_layout = layout_previews or {}
    out: dict[str, dict[str, float]] = {}
    for slide_id, png in previews.items():
        chrome = chrome_by_layout.get(layouts_by_slide.get(slide_id, ""))
        ink, dx, dy = ink_metrics(png, chrome)
        zone_w, zone_h = empty_zone(png, chrome)
        out[slide_id] = {
            "ink": round(ink, 4),
            # Без превью макета допуски равны — то же правило, что в самой проверке.
            "imbalance": round(imbalance(dx, dy, x_tol if chrome else y_tol, y_tol), 2),
            "zone_w": round(zone_w, 2),
            "zone_h": round(zone_h, 2),
            "chrome": 1.0 if chrome is not None else 0.0,
        }
    return out


@check(id="design.ink_balance", deterministic=True, severity=Severity.WARNING,
       title="Содержание слайда прижато к краю или слайд перегружен")
def ink_balance(ctx: CheckContext) -> Iterable[Finding]:
    """Содержание слайда прижато к краю или слайд перегружен."""
    previews = ctx.previews
    if not previews:
        raise CheckUnavailable("превью слайдов нет: считать метрики оформления не по чему")

    chrome_by_layout = getattr(ctx, "layout_previews", None) or {}

    zone_min_w = ctx.param("zone_min_w", 0.4)
    zone_min_h = ctx.param("zone_min_h", 0.4)
    max_imbalance = ctx.param("max_imbalance", 1.0)
    zone_needs = ctx.param("zone_needs_imbalance", 0.5)
    y_tol = ctx.param("y_tol", 0.15)
    min_ink = ctx.param("min_ink", 0.005)
    max_ink = ctx.param("max_ink", 0.15)

    for slide in ctx.deck.slides:
        png = previews.get(slide.slide_id)
        if png is None:
            continue
        chrome = chrome_by_layout.get(slide.layout_id)
        ink, dx, dy = ink_metrics(png, chrome)
        # Без превью макета декор шаблона считается содержанием, и строгий допуск
        # по горизонтали ловил бы логотип, а не вёрстку: допуски равны, как до C9.
        x_tol = ctx.param("x_tol", 0.1) if chrome is not None else y_tol
        offset = imbalance(dx, dy, x_tol, y_tol)
        evidence = {
            "ink": f"{ink:.4f}",
            "imbalance": f"{offset:.2f}",
            "chrome": "yes" if chrome is not None else "no",
        }

        if ink < min_ink:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="ink:empty",
                message=f"Слайд почти пуст: содержание занимает {ink:.1%} площади",
                evidence=evidence,
            )
            continue
        if ink > max_ink:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="ink:crowded",
                message=f"Слайд перегружен: содержание занимает {ink:.1%} площади",
                evidence=evidence,
            )
            continue
        # Широкая и низкая пустая зона — воздух над или под рядом показателей, и так
        # задумано. Дефект — зона, которая **стоит рядом** с содержанием: она и широка,
        # и высока разом (замеры: 47 × 100 % и 55 × 100 % против 100 × 32 % у показателей).
        # Поэтому пределы по осям отдельные, а не один на площадь. Плюс дисбаланс: пустота
        # и перекос вместе, как их и складывает AeSlides.
        zone_w, zone_h = empty_zone(png, chrome)
        evidence |= {"zone_w": f"{zone_w:.2f}", "zone_h": f"{zone_h:.2f}"}
        if zone_w > zone_min_w and zone_h > zone_min_h and offset > zone_needs:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="whitespace:zone",
                message=(
                    f"На слайде пустая зона {zone_w:.0%} ширины и {zone_h:.0%} высоты: "
                    "содержание не заняло отведённого"
                ),
                evidence=evidence,
            )
            continue
        if offset > max_imbalance:
            yield make_finding(
                check_id="design.ink_balance",
                slide_id=slide.slide_id,
                reason="balance:off_centre",
                message=(
                    f"Содержание прижато к краю: центр тяжести смещён на {dx:.2f} "
                    f"по горизонтали и {dy:.2f} по вертикали — {offset:.1f} допуска"
                ),
                evidence=evidence,
            )
