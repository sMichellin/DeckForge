"""Пороги контраста по роли текста. Change `a-minimum-is-not-a-norm`.

Единственное место, которое знает, сколько нужно. До этого change порог был зашит
в трёх местах — в измерении, в достройке и в рендере, — и все три знали разное.

Правила заказчика, пункт за пунктом:

* порог зависит от кегля и начертания, а не от того, что это «просто текст»;
* мелкому служебному тексту минимума мало: у него есть запас, и пара без запаса
  помечается, а не выдаётся за норму;
* цвет знака подбирается под его собственный порог, а не под порог графики.

Сама формула контраста не здесь: она в `domain.rules` и там проверена.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum

from deckforge.domain.base import DomainModel
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.rules import contrast_ratio, delta_e_rgb, relative_luminance
from deckforge.domain.template import Theme

#: Кегль, с которого текст считается крупным. В документе заказчика — «примерно
#: от 24 px Regular или от 19 px Bold»; 24 px — это 18 pt, 19 px — 14 pt.
LARGE_PT = 18.0
LARGE_BOLD_PT = 14.0

#: Минимумы WCAG 2.1. Не «хорошо», а «ниже нельзя».
MIN_LARGE = 3.0
MIN_BODY = 4.5

#: Запас для мелкого служебного текста: уровень AAA того же стандарта. Решение
#: заказчика на «желательно больше 4,5»: число нужно, иначе «проходит» не ответить.
COMFORT_CAPTION = 7.0

#: Графика, линия, маркер: тот же порог, что у крупного текста.
MIN_GRAPHICS = 3.0

#: Граница «светлая плашка / тёмная плашка» по относительной яркости. Порог алгоритма,
#: а не свойство чьей-то палитры: насыщенный цвет может иметь высокую яркость и просить
#: тёмную надпись, а бледный — низкую и просить светлую. Значение лежит между двумя
#: замерами разбора заказчика (0,62 и 0,20) с запасом от обоих.
_MID_LUMINANCE = 0.4


class TextClass(StrEnum):
    """Класс текста — он и решает, какой порог применить."""

    LARGE = "large"
    BODY = "body"
    CAPTION = "caption"
    GRAPHICS = "graphics"


class Readability(DomainModel):
    """Приговор одной паре: сколько получилось, сколько требовалось, есть ли запас."""

    ratio: float
    required: float
    comfort: float
    text_class: TextClass

    @property
    def passes(self) -> bool:
        return self.ratio >= self.required

    @property
    def tight(self) -> bool:
        """Прошло минимум, но запаса нет — для подписи такую пару не берут."""
        return self.passes and self.ratio < self.comfort


def text_class(
    size_pt: float | None, *, bold: bool = False, role: TextRole | None = None
) -> TextClass:
    """Класс текста по кеглю и начертанию шаблона, а не по нашему представлению о крупном."""
    if role is TextRole.CAPTION:
        return TextClass.CAPTION
    if size_pt is None:
        return TextClass.BODY
    if size_pt >= LARGE_PT or (bold and size_pt >= LARGE_BOLD_PT):
        return TextClass.LARGE
    return TextClass.BODY


def required_ratio(kind: TextClass) -> float:
    if kind in (TextClass.LARGE, TextClass.GRAPHICS):
        return MIN_LARGE if kind is TextClass.LARGE else MIN_GRAPHICS
    return MIN_BODY


def comfort_ratio(kind: TextClass) -> float:
    """Порог с запасом. Он выше минимума только у мелкого служебного текста."""
    return COMFORT_CAPTION if kind is TextClass.CAPTION else required_ratio(kind)


def readability(foreground_hex: str, background_hex: str, kind: TextClass) -> Readability:
    return Readability(
        ratio=round(contrast_ratio(foreground_hex, background_hex), 2),
        required=required_ratio(kind),
        comfort=comfort_ratio(kind),
        text_class=kind,
    )


def readable_from(
    palette: Mapping[ColorRef, str],
    background_hex: str,
    kind: TextClass,
    *,
    prefer_hex: str | None = None,
) -> ColorRef | None:
    """То же, что `readable_ref`, но по готовой таблице «слот → цвет».

    Странице отдана `DesignSystem`, а не `TemplateManifest`: темы как объекта у неё нет,
    а правило должно быть тем же самым, а не переписанным заново.
    """
    minimum, comfort = required_ratio(kind), comfort_ratio(kind)

    def nearest(candidates: list[ColorRef]) -> ColorRef | None:
        if not candidates:
            return None
        if prefer_hex is None:
            return max(candidates, key=lambda ref: contrast_ratio(palette[ref], background_hex))
        return min(candidates, key=lambda ref: (delta_e_rgb(palette[ref], prefer_hex), ref.value))

    passing = [ref for ref in palette if contrast_ratio(palette[ref], background_hex) >= comfort]
    return nearest(passing) or nearest(
        [ref for ref in palette if contrast_ratio(palette[ref], background_hex) >= minimum]
    )


def readable_ref(
    theme: Theme,
    background_hex: str,
    kind: TextClass,
    *,
    prefer_hex: str | None = None,
    slots: Sequence[ColorRef] | None = None,
    comfort_only: bool = False,
) -> ColorRef | None:
    """Слот темы, которым этот класс текста читается на этом фоне.

    Берётся не «самый контрастный»: между прошедшими выбирается ближайший по цвету
    к тому, что хотел шаблон. Правило заказчика ровно об этом — «для мелкого текста
    брать тот же цвет глубже», а не чёрный: тон остаётся, меняется светлота.
    Нет прошедшего — `None`, и это дефект шаблона, а не повод поставить лучший
    из плохих и промолчать.
    """
    minimum, comfort = required_ratio(kind), comfort_ratio(kind)
    choices = list(slots) if slots else list(ColorRef)

    def nearest(candidates: list[ColorRef]) -> ColorRef | None:
        if not candidates:
            return None
        if prefer_hex is None:
            return max(
                candidates, key=lambda ref: (contrast_ratio(theme.colors.get(ref), background_hex),)
            )
        return min(
            candidates, key=lambda ref: (delta_e_rgb(theme.colors.get(ref), prefer_hex), ref.value)
        )

    passing = [
        ref for ref in choices if contrast_ratio(theme.colors.get(ref), background_hex) >= comfort
    ]
    if comfort_only:
        #: Вопрос «есть ли запас», а не «сойдёт ли»: подпись на минимуме — это ровно тот
        #: случай, который заказчик показала пальцем.
        return nearest(passing)
    return nearest(passing) or nearest(
        [ref for ref in choices if contrast_ratio(theme.colors.get(ref), background_hex) >= minimum]
    )


def ink_on_plate(theme: Theme, plate_hex: str, kind: TextClass) -> ColorRef | None:
    """Цвет надписи на плашке по правилу заказчика: тёмная — светлый, светлая — тёмный.

    «Светлая плашка → графитовый текст; тёмная плашка → белый; средняя по яркости →
    требуется расчёт». Полярность решается раньше контраста: тёмная надпись на синей
    плашке формально берёт 5,08 и всё равно читается плохо — именно это заказчик
    показала пальцем.

    Возвращается лучший по контрасту слот **нужной полярности**, взявший свой порог.
    Такого нет — `None`: плашку с надписью не делают, акцент остаётся границей.
    """
    plate = relative_luminance(plate_hex)
    threshold = comfort_ratio(kind) if kind is TextClass.CAPTION else required_ratio(kind)
    polar = [
        ref
        for ref in ColorRef
        if (relative_luminance(theme.colors.get(ref)) > plate) is (plate < _MID_LUMINANCE)
    ]
    passing = [
        ref for ref in polar if contrast_ratio(theme.colors.get(ref), plate_hex) >= threshold
    ]
    if not passing:
        return None
    return max(passing, key=lambda ref: contrast_ratio(theme.colors.get(ref), plate_hex))


#: Насколько далеко от исходного цвета можно уйти, подбирая плашку глубже. Расстояние
#: в RGB: за этой границей «тот же цвет темнее» превращается в другой цвет.
PLATE_HUE_DISTANCE = 190.0


def deeper_plate(theme: Theme, plate_hex: str, kind: TextClass) -> tuple[ColorRef, ColorRef] | None:
    """Та же плашка глубже — и надпись, которая на ней читается.

    Правило заказчика: мелкому тексту на средней по яркости плашке безопаснее не менять
    цвет надписи, а взять фон глубже. Меняется не тон, а светлота: берётся
    ближайший по цвету слот темы, на котором надпись наконец берёт свой порог.
    """
    lightness = relative_luminance(plate_hex)
    candidates: list[tuple[float, str, ColorRef, ColorRef]] = []
    for ref in ColorRef:
        candidate = theme.colors.get(ref)
        distance = delta_e_rgb(candidate, plate_hex)
        if distance == 0 or distance > PLATE_HUE_DISTANCE:
            continue
        #: Глубже — значит в ту же сторону, что и полярность плашки: тёмная становится
        #: темнее, светлая светлее. Иначе «тот же цвет глубже» превращается в другой цвет.
        deeper_side = relative_luminance(candidate) < lightness
        if deeper_side is not (lightness < _MID_LUMINANCE):
            continue
        ink = ink_on_plate(theme, candidate, kind)
        if ink is not None:
            candidates.append((distance, ref.value, ref, ink))
    if not candidates:
        return None
    candidates.sort()
    _distance, _name, plate, ink = candidates[0]
    return plate, ink


def best_available(theme: Theme, background_hex: str) -> tuple[ColorRef, float]:
    """Лучшее, что вообще даёт эта тема на этом фоне. Нужно, чтобы назвать дефект числом."""
    scored = sorted(
        (
            (contrast_ratio(theme.colors.get(ref), background_hex), ref.value, ref)
            for ref in ColorRef
        ),
        key=lambda row: (-row[0], row[1]),
    )
    ratio, _name, ref = scored[0]
    return ref, round(ratio, 2)
