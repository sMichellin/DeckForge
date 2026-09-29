"""`content.numbers_grounded` — фактчекинг чисел. Change (18) `audit-semantic`.

Проверка объявлена **детерминированной**, хотя лежит в `semantic/`: спрашивать VLM
«все ли цифры настоящие» бессмысленно — исходных материалов она не видит и может лишь
согласиться с тем, что написано на слайде. Числа извлекаются из текста слайда тем же
разбором, что и из контента (change 7), и сверяются с `ContentPackage.facts[].numbers`.

Заодно это один из рычагов бюджета: вопрос про числа стоил бы 12 вызовов VLM на колоду
из 12 слайдов, а при трёх прогонах — 36.

Форматные расхождения («37 %» против доли 0.37) разрешаются арифметикой, а не моделью:
проценты и доли — одно и то же число в разных единицах, и путать их с настоящим
расхождением нельзя.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import block_bbox, block_text, layout_of
from deckforge.audit.recipes import catalogue_with_passports
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.designsystem.models import PlaceKind
from deckforge.domain.audit import Finding
from deckforge.domain.content import Number
from deckforge.domain.enums import Severity
from deckforge.domain.slide import BulletsBlock, KpiBlock, SlideIR, SmartArtBlock, TextBlock
from deckforge.parsing.content import extract_numbers

#: Допуск сравнения: числа на слайде округляют, «37,5 %» превращается в «38 %».
_TOLERANCE = 0.51

#: Меньше этого счёт ничего не сообщает: «1 шаг» — это не перечисление, а единица
#: попадается в тексте на каждом шагу и открыла бы дыру в проверке.
_MIN_COUNT = 2


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= _TOLERANCE


def grounded_in(number: Number, sources: list[Number]) -> bool:
    """Есть ли число в исходных материалах — с учётом формата записи.

    Совпадение ищется по значению, а не по строке: на слайде «37 %», в источнике
    может лежать 0.37. Это одно и то же число, и находкой быть не должно.
    """
    for source in sources:
        if _close(number.value, source.value):
            return True
        # Процент против доли: 37 % ↔ 0.37. Сотая часть — не опечатка, а единица.
        if _close(number.value, source.value * 100) or _close(number.value * 100, source.value):
            return True
    return False


def counts_on(slide: SlideIR) -> set[int]:
    """Сколько на слайде пунктов, показателей и узлов схемы — по каждому такому блоку.

    Задача A10. Прогон `aa5eca9aa135` s08: проверка нашла на слайде число «4», которого
    в материалах нет, — а под заголовком стояли ровно четыре пункта. Это не выдуманная
    цифра, а счёт того, что на слайде и так видно: запретить его значит запретить
    заголовок «Четыре шага внедрения».

    Считается по каждому блоку отдельно, а не сумма по слайду: заголовок ссылается
    на один список, а не на всё содержание разом.
    """
    out: set[int] = set()
    for block in slide.blocks:
        if isinstance(block, BulletsBlock | KpiBlock | SmartArtBlock):
            out.add(len(block.items))
    return {count for count in out if count >= _MIN_COUNT}


def is_a_count(number: Number, counts: set[int]) -> bool:
    """Число — это счёт пунктов слайда, а не величина.

    Единица измерения снимает вопрос: «4 %» и «4 млн ₽» над четырьмя пунктами —
    по-прежнему находка. Счётом может быть только целое без единицы.
    """
    if number.unit is not None:
        return False
    return float(number.value).is_integer() and int(number.value) in counts


@check(id="content.numbers_grounded", deterministic=True, severity=Severity.ERROR,
       title="Все цифры и факты со слайда есть в исходных материалах")
def numbers_grounded(ctx: CheckContext) -> Iterable[Finding]:
    """Все цифры и факты со слайда есть в исходных материалах."""
    content = ctx.content
    if content is None:
        raise CheckUnavailable("контент-пакета нет: сверять числа не с чем")

    language = getattr(ctx.deck, "language", None) or "ru"
    if language != "ru":
        # Разбор чисел пока только для русского (change 7). Молчать нельзя:
        # непроверенные числа — не то же самое, что проверенные и верные.
        raise CheckUnavailable(f"разбор чисел для языка {language!r} не реализован")

    sources = content.all_numbers
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        counts = counts_on(slide)
        for block in slide.blocks:
            text = block_text(block)
            if not text:
                continue
            for number in extract_numbers(text, language):
                if grounded_in(number, sources) or is_a_count(number, counts):
                    continue
                shown = number.raw or f"{number.value:g}"
                yield make_finding(
                    check_id="content.numbers_grounded",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=block_bbox(block, layout),
                    reason=f"number:{shown}",
                    message=(
                        f"Числа «{shown}» нет в исходных материалах: "
                        "либо оно выдумано, либо факт потерялся при разборе контента"
                    ),
                    evidence={
                        "raw": shown,
                        "value": f"{number.value:g}",
                        "unit": number.unit or "—",
                    },
                )


# --- слово, оборванное посреди (план Б, круг 2, К1; change `the-cut-word-is-found`) --------

_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]+")

#: Падежные и родовые окончания: «процесс» при «процессов» в материалах — форма слова,
#: а не обрыв. Список грамматики языка, а не слов шаблона (правило 2).
_ENDINGS = frozenset({
    "а", "я", "о", "е", "ы", "и", "у", "ю", "ь", "й",
    "ом", "ем", "ой", "ей", "ам", "ям", "ов", "ев", "ах", "ях", "ый", "ий", "ая", "яя",
    "ое", "ее", "ые", "ие", "ым", "им", "ую", "юю",
    "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими",
    "s", "es", "ed", "ing",
})

#: Служебные слова — местоимения, предлоги, частицы: «ИИ делает слайды сам» при
#: «самостоятельно» в материалах — законный конец фразы, а не обрывок. Тоже грамматика языка.
_FUNCTION_WORDS = frozenset({
    "сам", "сама", "само", "сами", "весь", "вся", "всё", "все", "его", "её", "их", "они",
    "она", "оно", "это", "эти", "тот", "та", "то", "те", "как", "так", "там", "тут", "где",
    "уже", "ещё", "еще", "или", "для", "под", "над", "при", "без", "про", "через", "между",
    "the", "and", "for", "with", "all", "its",
})

#: Ближайшее слово материалов должно быть длиннее хотя бы на столько букв: иначе
#: «труд» при «труда» — окончание, а не обрыв.
_MIN_TAIL = 2
#: Короче — не судим: предлоги и союзы начинают слишком много слов.
_MIN_STEM = 3


def _source_words(ctx: CheckContext) -> set[str]:
    content = ctx.content
    if content is None:
        return set()
    texts = [fact.text for fact in getattr(content, "facts", [])]
    texts.append(getattr(content, "raw_markdown", None) or "")
    return {word.lower() for text in texts for word in _WORD.findall(text)}


def cut_word(text: str, words: set[str]) -> str | None:
    """Последнее слово текста, если оно — обрывок слова материалов; иначе `None`."""
    found: list[str] = _WORD.findall(text)
    if not found or not words:
        return None
    last = found[-1].lower()
    if len(last) < _MIN_STEM or last in words or last in _FUNCTION_WORDS:
        return None
    tails = [word[len(last):] for word in words if word.startswith(last) and word != last]
    if not tails or min(len(tail) for tail in tails) < _MIN_TAIL:
        return None
    if any(tail in _ENDINGS for tail in tails):
        return None
    return found[-1]


def _texts(block: object) -> list[str]:
    if isinstance(block, TextBlock):
        return [block.text]
    if isinstance(block, BulletsBlock):
        return [item.text for item in block.items]
    return []


@check(id="content.word_cut", deterministic=True, severity=Severity.ERROR,
       title="Текст оборван посреди слова")
def word_cut(ctx: CheckContext) -> Iterable[Finding]:
    """Текст оборван посреди слова (план Б, круг 2, К1; строка мерила 6б).

    Первый живой прогон `by_example` 29.09: семь текстов на трёх колодах оборваны —
    «AI не копирует фирменны», «Подобранный пат.». Строки мерила 1–7 их не видят. Признака два:

    * **предел места** — текст в текстовом месте паспорта длиной ровно ёмкость места:
      грамматика ответа (`maxLength`) оборвала его на знаке. Место под число так не судится —
      «10x» ровно в три знака законно;
    * **оборванное слово** — последнее слово не встречается в материалах, но слово материалов
      с него начинается и длиннее на две буквы и больше, и это не падежное окончание:
      модель сократила слово сама («пат.» при «паттерн»). Словарём этого не поймать:
      «пат», «мин», «презент» — словарные слова.
    """
    words = _source_words(ctx)
    recipes = catalogue_with_passports(ctx)
    for slide in ctx.deck.slides:
        recipe = recipes.get(slide.recipe_id or "")
        places = {
            place.zone_id: place
            for place in (recipe.passport.places if recipe and recipe.passport else [])
            if place.zone_id is not None
        }
        for block in slide.blocks:
            place = places.get(getattr(block, "zone_id", None) or "")
            for text in _texts(block):
                stripped = text.strip()
                at_limit = (
                    place is not None
                    and place.kind is PlaceKind.TEXT
                    and len(stripped) == place.capacity_chars
                )
                broken = cut_word(stripped, words)
                if not at_limit and broken is None:
                    continue
                why = (
                    f"длина ровно предел места {place.capacity_chars} знаков"
                    if at_limit and place is not None
                    else f"«{broken}» — начало слова из материалов"
                )
                yield make_finding(
                    check_id="content.word_cut",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    reason="limit" if at_limit else "word",
                    message=f"Текст «{stripped[-40:]}» оборван: {why}",
                    evidence={"text": stripped, "sign": "limit" if at_limit else "word"},
                )
