"""Классификация макетов. Change (5) `layout-classification` (эвристическая часть).

Вид макета выводится из **состава и геометрии плейсхолдеров**, а не из его имени:
имена в шаблонах произвольны, переведены на разные языки и часто вообще не описывают
содержание («2_Титульный слайд», «Custom Layout 14»). Опора на имя — это заточка
под знакомый шаблон (C6).

VLM подключается в той же change поверх этой эвристики — только там, где уверенность низкая.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from deckforge.domain.enums import LayoutKind, TextRole
from deckforge.domain.template import (
    LayoutShape,
    LayoutSpec,
    PlaceholderSpec,
    ShapeKind,
    SlideSize,
)
from deckforge.inference.client import InferenceQuotaError
from deckforge.inference.vlm import VlmClient
from deckforge.parsing.layout_preview import (
    LayoutPreviewProvider,
    SchematicPreview,
    describe_layout,
)
from deckforge.parsing.ooxml.layouts import DECOR_PH_TYPES
from deckforge.registry import get_prompt_registry

#: Порог, ниже которого эвристике не верят и зовут VLM.
UNCERTAIN_BELOW = 0.6

#: Доля слайда, начиная с которой картинка делает макет полноэкранным.
_IMAGE_FULL_SHARE = 0.6

#: Доля, начиная с которой картинка занимает заметную часть и делит слайд с текстом.
_IMAGE_HALF_SHARE = 0.3

#: Доля слайда под основным текстом, начиная с которой он тянет на полноценную колонку.
#: Ниже — это подпись или строка под заголовком, а не вторая колонка.
_COLUMN_BODY_SHARE = 0.12

#: Картинка, закрывающая почти весь слайд, — это фон, а не содержание. В шаблонах
#: такой фон лежит под каждым вторым макетом, и считать их все фотослайдами неверно.
#:
#: Различать фон по доле текста бесполезно: на титульном слайде текста 3 % площади,
#: и он всё равно титульный, а не фотослайд. Работает другой признак — есть ли поверх
#: картинки места под контент. Если есть, картинка им подложка; если нет, картинка и
#: есть содержание слайда.
_BACKGROUND_SHARE = 0.85

#: Полоса у верхнего края, объявленная телом, а не заголовком. Так размечают шаблоны,
#: где заголовок набирается «своим» стилем: тип BODY, но стоит там и таков, где и каким
#: бывает только заголовок — в верхних 15 % слайда, не выше 12 % его высоты и не уже
#: 40 % ширины. Последнее отсекает ряд показателей у верхнего края: там блоки узкие.
_TITLE_BAND_TOP = 0.15
_TITLE_BAND_HEIGHT = 0.12
_TITLE_BAND_WIDTH = 0.4

#: Уверенность для макета, где кроме заголовка есть только места под картинки.
#: Ниже, чем у картинки на весь слайд: вид ясен, но сколько картинок и какого
#: они размера, эвристика не взвешивает.
_PICTURES_ONLY_CONFIDENCE = 0.75

_CHART_PH = frozenset({"CHART"})
_TABLE_PH = frozenset({"TBL"})
_PICTURE_PH = frozenset({"PIC"})


def _content_placeholders(placeholders: list[PlaceholderSpec]) -> list[PlaceholderSpec]:
    """Колонтитулы, дата и номер слайда не делают макет содержательным."""
    return [p for p in placeholders if p.ph_type.lower() not in DECOR_PH_TYPES]


def _same_row(a: PlaceholderSpec, b: PlaceholderSpec, tolerance: int) -> bool:
    return abs(a.y - b.y) <= tolerance and abs(a.cy - b.cy) <= tolerance


def classify_heuristic(
    placeholders: list[PlaceholderSpec],
    slide_size: SlideSize,
    shapes: list[LayoutShape] | None = None,
) -> tuple[LayoutKind, float]:
    """Вид макета и уверенность в нём.

    `shapes` — фигуры вне плейсхолдеров. Без них макет, где фотография положена обычным
    `p:pic`, неотличим от пустого слайда с заголовком.
    """
    shapes = shapes or []
    content = _content_placeholders(placeholders)
    slide_area_early = slide_size.cx_emu * slide_size.cy_emu
    if not content:
        # Мест под контент нет вовсе. Если при этом слайд занимает картинка — она и есть
        # содержание; иначе это декоративный разделитель или макет «под ручную вёрстку».
        biggest_picture = max(
            (s.cx * s.cy for s in shapes if s.kind is ShapeKind.PICTURE), default=0
        )
        if biggest_picture / slide_area_early >= _IMAGE_HALF_SHARE:
            return LayoutKind.IMAGE_FULL, 0.85
        return LayoutKind.SECTION, 0.4

    slide_area = slide_size.cx_emu * slide_size.cy_emu
    tolerance = int(slide_size.cy_emu * 0.03)

    titles = [p for p in content if p.role is TextRole.TITLE]
    bodies = [p for p in content if p.role is TextRole.BODY]
    subtitles = [p for p in content if p.role is TextRole.SUBTITLE]
    if not titles:
        band = _title_band(bodies, slide_size)
        if band is not None:
            titles = [band]
            bodies = [p for p in bodies if p is not band]

    # Явные типы плейсхолдеров — самый надёжный сигнал: автор шаблона сказал прямо.
    if any(p.ph_type in _CHART_PH for p in content):
        return LayoutKind.CHART, 0.95
    if any(p.ph_type in _TABLE_PH for p in content):
        return LayoutKind.TABLE, 0.95

    # Плейсхолдер под картинку и фоновая фигура — разные вещи, и путать их нельзя.
    # В первый автор шаблона предполагал что-то положить, вторая уже нарисована.
    slot_share = max(
        (p.cx * p.cy for p in content if p.ph_type in _PICTURE_PH), default=0
    ) / slide_area
    decor_share = max(
        (s.cx * s.cy for s in shapes if s.kind is ShapeKind.PICTURE), default=0
    ) / slide_area

    # Нарисованная картинка во весь слайд — подложка под контент, а не содержание.
    # Иначе фотослайдами объявляется почти весь шаблон: в VK Tech таких макетов 23 из 37.
    other_slots = [p for p in content if p.ph_type not in _PICTURE_PH]
    if decor_share >= _BACKGROUND_SHARE and other_slots:
        decor_share = 0.0

    share = max(slot_share, decor_share)
    if share >= _IMAGE_FULL_SHARE:
        return LayoutKind.IMAGE_FULL, 0.9

    # Картинка в пол-слайда рядом с текстом — это две колонки, одна из которых картинка.
    # Но колонкой текст становится, только если его есть чем наполнить: на титульном
    # слайде под декоративным фото стоит узкая строка подписи, и это по-прежнему титул.
    body_share = sum(p.cx * p.cy for p in bodies) / slide_area
    if share >= _IMAGE_HALF_SHARE and body_share >= _COLUMN_BODY_SHARE:
        return LayoutKind.TWO_COLUMN, 0.75

    # Кроме заголовка — только места под картинки: содержание слайда в них, сколько бы
    # их ни было и какими бы маленькими они ни были. Без этого правила такой макет
    # падал в «заголовок без текста» — закрывающий слайд с уверенностью 0.45.
    pictures = [p for p in content if p.ph_type in _PICTURE_PH]
    if pictures and not bodies and not subtitles:
        return LayoutKind.IMAGE_FULL, _PICTURES_ONLY_CONFIDENCE

    # Титул: заголовок с подзаголовком и без основного текста.
    if titles and subtitles and not bodies:
        return LayoutKind.TITLE, 0.9

    # Раздел: единственный крупный текстовый блок, ничего больше.
    if len(content) == 1 and titles:
        vertical_center = titles[0].y + titles[0].cy / 2
        centered = abs(vertical_center - slide_size.cy_emu / 2) <= slide_size.cy_emu * 0.2
        return (LayoutKind.SECTION, 0.85) if centered else (LayoutKind.TITLE, 0.6)

    if bodies:
        # Несколько одинаковых блоков в один ряд: колонки или показатели.
        rows = [p for p in bodies if _same_row(p, bodies[0], tolerance)]
        if len(rows) >= 3 and all(p.cx * p.cy / slide_area < 0.15 for p in rows):
            return LayoutKind.KPI, 0.8
        if len(rows) == 2:
            return LayoutKind.TWO_COLUMN, 0.85
        if len(bodies) == 1 and titles:
            body = bodies[0]
            # Широкий и высокий одиночный блок под заголовком — классические буллеты.
            if body.cy / slide_size.cy_emu >= 0.25:
                return LayoutKind.BULLETS, 0.8
            return LayoutKind.QUOTE, 0.5

    if titles and not bodies and not subtitles:
        return LayoutKind.CLOSING, 0.45

    return LayoutKind.CUSTOM, 0.3


def _title_band(bodies: list[PlaceholderSpec], slide_size: SlideSize) -> PlaceholderSpec | None:
    """Тело, которое по месту и форме — заголовок. Берётся самое верхнее из таких."""
    band = [
        p
        for p in bodies
        if p.y <= slide_size.cy_emu * _TITLE_BAND_TOP
        and p.cy <= slide_size.cy_emu * _TITLE_BAND_HEIGHT
        and p.cx >= slide_size.cx_emu * _TITLE_BAND_WIDTH
    ]
    return min(band, key=lambda p: p.y, default=None)


def needs_vlm(confidence: float) -> bool:
    """Звать ли VLM. Дорогой вызов делается только там, где эвристика не уверена."""
    return confidence < UNCERTAIN_BELOW


@dataclass(frozen=True, slots=True)
class Classification:
    """Вид макета с указанием, чем он получен. `kind_source` попадает в манифест."""

    kind: LayoutKind
    confidence: float
    source: str


def geometry_signature(placeholders: list[PlaceholderSpec], slide_size: SlideSize) -> str:
    """Отпечаток геометрии макета.

    Макеты с одинаковой расстановкой блоков — а в шаблонах с двумя мастерами их много —
    получают один и тот же ответ без повторного вызова модели.
    """
    parts = sorted(
        f"{ph.ph_type}:{ph.x / slide_size.cx_emu:.3f},{ph.y / slide_size.cy_emu:.3f},"
        f"{ph.cx / slide_size.cx_emu:.3f},{ph.cy / slide_size.cy_emu:.3f}"
        for ph in placeholders
    )
    return "|".join(parts)


class LayoutClassifier:
    """Эвристика плюс VLM. Change (5) `layout-classification`.

    Порядок ровно такой, как в ADR-004 для аудита, и по той же причине: дешёвое и
    воспроизводимое идёт первым, модель подключается только там, где без неё не обойтись.
    """

    def __init__(
        self,
        vlm: VlmClient | None = None,
        preview: LayoutPreviewProvider | None = None,
        *,
        votes: int = 3,
        escalate_on_disagreement: bool = True,
        language: str = "ru",
        profile: str | None = None,
        base_seed: int = 1337,
    ) -> None:
        self.vlm = vlm
        self.preview = preview or SchematicPreview()
        self.votes = max(1, votes)
        #: Голосовать сразу тремя прогонами нужно не всегда. Если первый ответ совпал
        #: с догадкой эвристики, два независимых метода уже сошлись — подтверждать
        #: нечего. Остальные прогоны тратятся только на разногласие, где дисперсия
        #: VLM действительно мешает. На шаблонах организаторов это срезает от трети
        #: до половины вызовов и удерживает парсинг в бюджете 25 с (§12).
        self.escalate_on_disagreement = escalate_on_disagreement
        self.language = language
        self.profile = profile
        self.base_seed = base_seed
        self._cache: dict[str, Classification] = {}
        self.calls = 0
        #: Отказы модели по типам. Молча проглоченное исключение выглядит как «всё хорошо»,
        #: поэтому счётчик обязателен: без него откат на эвристику не отличить от согласия.
        self.failures: Counter[str] = Counter()
        #: Взводится, когда кончилась квота. Дальше макеты классифицируются эвристикой:
        #: стучаться в исчерпанный лимит на каждом следующем макете — трата времени.
        self.exhausted = False

    @property
    def enabled(self) -> bool:
        return self.vlm is not None

    def classify(
        self, placeholders: list[PlaceholderSpec], slide_size: SlideSize, layout: LayoutSpec
    ) -> Classification:
        kind, confidence = classify_heuristic(placeholders, slide_size, layout.shapes)
        if not self.enabled or self.exhausted or not needs_vlm(confidence):
            return Classification(kind, confidence, "heuristic")

        signature = geometry_signature(placeholders, slide_size)
        if (cached := self._cache.get(signature)) is not None:
            return cached

        result = self._ask_vlm(layout, slide_size, kind, confidence)
        self._cache[signature] = result
        return result

    def _ask_vlm(
        self,
        layout: LayoutSpec,
        slide_size: SlideSize,
        heuristic_kind: LayoutKind,
        heuristic_confidence: float,
    ) -> Classification:
        assert self.vlm is not None
        bundle = get_prompt_registry().load("layout_classifier", profile=self.profile)
        system, user = bundle.render(
            language=self.language,
            description=describe_layout(layout, slide_size.cx_emu, slide_size.cy_emu),
            heuristic_kind=heuristic_kind.value,
            heuristic_confidence=heuristic_confidence,
        )

        try:
            image = self.preview.render(layout, slide_size.cx_emu, slide_size.cy_emu)
        except Exception as exc:
            self.failures[f"preview:{type(exc).__name__}"] += 1
            # Нет превью — это не повод остаться без вида макета вовсе.
            return Classification(heuristic_kind, heuristic_confidence, "heuristic")

        def vote(offset: int) -> LayoutKind | None:
            try:
                self.calls += 1
                answer = self.vlm.ask_image(  # type: ignore[union-attr]
                    system=system,
                    user=user,
                    image_png=image,
                    schema=bundle.response_schema,
                    seed=self.base_seed + offset,
                )
                # Ответ вне перечня видов — голос не засчитан, а не принят как custom.
                return LayoutKind(answer["kind"])
            except InferenceQuotaError:
                self.failures["quota"] += 1
                self.exhausted = True
                return None
            except Exception as exc:
                self.failures[type(exc).__name__] += 1
                return None

        verdicts: list[LayoutKind] = []
        first = vote(0)
        if self.exhausted:
            return Classification(heuristic_kind, heuristic_confidence, "heuristic")
        if first is not None:
            verdicts.append(first)

        needs_more = not (
            self.escalate_on_disagreement and first is not None and first is heuristic_kind
        )
        if needs_more:
            verdicts += [v for offset in range(1, self.votes) if (v := vote(offset)) is not None]

        if not verdicts:
            return Classification(heuristic_kind, heuristic_confidence, "heuristic")

        winner, wins = Counter(verdicts).most_common(1)[0]
        agreement = wins / len(verdicts)

        if winner is heuristic_kind:
            # Два независимых метода сошлись — это сильнее каждого из них по отдельности.
            confidence = min(1.0, heuristic_confidence + agreement * (1 - heuristic_confidence))
            return Classification(winner, round(confidence, 2), "vlm+heuristic")
        return Classification(winner, round(agreement, 2), "vlm")
