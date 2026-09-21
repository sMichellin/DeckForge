"""Профиль оформления шаблона по его слайдам-примерам. Change `design-profile-from-examples`
(задача DS7, она же C8).

Семь дешёвых признаков оформления из arXiv:2508.19289 сами по себе не «хороши» и не
«плохи»: пустота на минималистичном шаблоне — приём, а на плотном — дефект. Абсолютный
порог поэтому либо молчит там, где надо говорить, либо говорит там, где всё в порядке.
Честнее сравнивать колоду не с числом из головы, а с тем, как выглядят **родные слайды
этого же шаблона**.

Родные слайды у нас есть: 138 примеров на трёх шаблонах кейса. Пустой макет для этого
не годится — на нём нет содержания, и любая метрика скажет «пусто». Нужен именно пример:
слайд, который автор шаблона собрал сам и счёл правильным.

Разброс меряется медианой и межквартильным размахом, а не средним и σ: примеров
десятки, и один титульный слайд с одной строкой смещает среднее сильнее, чем вся
остальная колода.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median

#: Метрики, по которым строится профиль. Те же, что кладутся в отчёт прогона (C7).
METRICS = ("ink", "imbalance", "zone_w", "zone_h")

#: Во сколько межквартильных размахов от медианы слайд ещё «свой».
#:
#: Число откалибровано на примерах трёх шаблонов кейса, а не взято из статистики.
#: Критерий простой: проверка не должна объявлять чужими **родные** слайды шаблона —
#: отчёт, который врёт на эталоне, учит себя не читать (тот же урок, что в C3 и C10).
#: Доля своих слайдов, выпавших из профиля, по 138 примерам:
#:
#:     допуск   WorkSpace  Education  Tech
#:        1,5         17 %       15 %  24 %
#:        2,0         10 %        4 %   4 %
#:        2,5          7 %        0 %   2 %
#:        3,0          0 %        0 %   0 %
#:
#: Полтора размаха — правило ящика с усами — здесь не годится: примеры шаблона слишком
#: разные (титул, разделитель, плотная таблица), и четверть из них попадает в выбросы.
DEFAULT_TOLERANCE = 3.0

#: Профиль из двух-трёх примеров — не профиль, а совпадение.
MIN_EXAMPLES = 5


@dataclass(frozen=True, slots=True)
class Band:
    """Медиана и допустимый разброс одной метрики."""

    median: float
    spread: float

    def deviation(self, value: float, tolerance: float = DEFAULT_TOLERANCE) -> float:
        """Во сколько допусков значение выходит за разброс. ≤ 1 — слайд свой.

        Нулевой разброс (все примеры одинаковы) допуском не считается: иначе любое
        отличие на волос давало бы бесконечность. Тогда сравнение идёт с самой медианой.
        """
        if self.spread <= 0:
            return 0.0 if abs(value - self.median) < 1e-9 else 1.0 + abs(value - self.median)
        return abs(value - self.median) / (tolerance * self.spread)


@dataclass(frozen=True, slots=True)
class DesignProfile:
    """Как выглядят родные слайды этого шаблона."""

    bands: dict[str, Band]
    examples: int

    @property
    def usable(self) -> bool:
        return self.examples >= MIN_EXAMPLES and bool(self.bands)

    def deviations(
        self, metrics: dict[str, float], tolerance: float = DEFAULT_TOLERANCE
    ) -> dict[str, float]:
        """По каждой метрике — во сколько допусков слайд выходит за разброс шаблона."""
        return {
            name: band.deviation(metrics[name], tolerance)
            for name, band in self.bands.items()
            if name in metrics
        }


def profile_of(rows: Iterable[dict[str, float]]) -> DesignProfile:
    """Профиль по метрикам слайдов-примеров шаблона.

    На вход идут уже посчитанные метрики, а не картинки: сам счёт живёт в
    `deterministic/design.py` вместе с остальными метриками оформления, и профилю
    незачем тянуть за собой Pillow. Превью примеров снимаются тем же `soffice`,
    что и превью макетов, — но пустой макет здесь не подходит, нужен слайд
    с содержанием.
    """
    measured = list(rows)
    return DesignProfile(bands=_bands(measured), examples=len(measured))


def _bands(rows: Sequence[dict[str, float]]) -> dict[str, Band]:
    if len(rows) < MIN_EXAMPLES:
        return {}
    return {
        name: Band(median=median(values), spread=_iqr(values))
        for name in METRICS
        if (values := sorted(row[name] for row in rows))
    }


def _iqr(values: Sequence[float]) -> float:
    """Межквартильный размах. Устойчив к одному нетипичному примеру, в отличие от σ."""
    count = len(values)
    if count < 4:
        return 0.0
    lower = values[: count // 2]
    upper = values[(count + 1) // 2 :]
    return median(upper) - median(lower)
