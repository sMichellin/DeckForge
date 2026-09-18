"""Вопросы Приложения 1 ТЗ, на которые отвечает модель. Change (18) `audit-semantic`.

Формат ответа строго `{"verdict": "yes"|"no", "reason": "…"}` через constrained decoding.

Из одиннадцати вопросов ТЗ здесь живут восемь. Три уведены из модели, и каждый раз
по одной причине — **модель не может знать ответ лучше кода**:

* «все цифры есть в исходных материалах» → `semantic/grounding.py`: исходных материалов
  модель не видит и может лишь согласиться с тем, что написано на слайде;
* «текст без опечаток» → `semantic/spelling.py`: LanguageTool, опечатка либо есть, либо нет;
* «вся колода на одном языке» → эта же проверка ниже, но без модели: язык определяется
  по тексту, а не по картинке.

Каждый уведённый вопрос — минус 12 вызовов VLM на колоду из 12 слайдов, при трёх
прогонах минус 36. Замер бюджета в `docs/agents/kickoff-c-15.md`.

**Голосование тратится на обвинения, а не на каждый вопрос.** Вердикт «yes» значит
«претензий нет» и находки не порождает: цена ошибки здесь — пропущенная мелочь.
Вердикт «no» порождает находку, которую увидит человек, поэтому он и переспрашивается
тремя прогонами с разными seed. Так стоимость падает втрое там, где колода в порядке.

**Вопросы по слайдам можно задавать одновременно.** Они независимы: вердикт по одному
слайду не влияет на вердикт по другому. Это бьёт по стенным часам, а не по числу вызовов,
и потому включается отдельным ключом — см. `DEFAULT_CONCURRENCY`. Числа, ради которых
всё это, — в `openspec/changes/audit-judge-concurrency/proposal.md`: 28 с на вызов
по замеру 18.09 против 60 с стадии `audit` в `pipeline/budget.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import slide_text
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, Severity
from deckforge.registry import get_prompt_registry

QUESTIONS: dict[str, str] = {
    "content.headline_is_conclusion": "Заголовок содержит вывод, а не просто называет тему?",
    "content.body_matches_headline": "Содержимое слайда соответствует заголовку?",
    "content.one_sentence_summary": "Слайд пересказывается одним предложением?",
    "content.has_substance": "На слайде есть содержание, а не только заголовок?",
    "content.visuals_on_topic": "Картинки и иконки относятся к теме слайда?",
    "content.no_prompt_leftovers": "Нет служебного мусора: реплик спикера, кусков промпта?",
    "content.table_rows_meaningful": "Все строки таблицы и элементы легенды работают на мысль?",
    "content.neighbours_connected": "Соседние слайды связаны между собой по логике?",
}

# Тяжесть и авто-фикс синхронизированы с `configs/audit_checks.yaml`
# (расхождение ловит tests/unit/test_audit_registry.py).
_SEVERITY: dict[str, Severity] = {
    "content.headline_is_conclusion": Severity.WARNING,
    "content.body_matches_headline": Severity.WARNING,
    "content.one_sentence_summary": Severity.INFO,
    "content.has_substance": Severity.WARNING,
    "content.visuals_on_topic": Severity.WARNING,
    "content.no_prompt_leftovers": Severity.ERROR,
    "content.table_rows_meaningful": Severity.INFO,
    "content.neighbours_connected": Severity.INFO,
}
_AUTO_FIX: dict[str, AutoFix] = {
    "content.headline_is_conclusion": AutoFix.REGENERATE_HEADLINE,
}

#: Вопрос про пару слайдов, а не про один: спрашивается по второму слайду пары,
#: первый уходит в контекст текстом.
_PAIRWISE = "content.neighbours_connected"

#: Сколько вопросов задавать серверу одновременно. По умолчанию — один, то есть
#: поведение прежнее.
#:
#: Это не осторожность ради осторожности. Параллелизм выигрывает только там, где сервер
#: обслуживает запросы параллельно: llama.cpp с одним слотом выстроит их в очередь,
#: и 39 минут останутся 39 минутами. А на провайдере с поминутным лимитом (Groq) лишние
#: одновременные запросы получают отказ, `ask` ловит его и возвращает `None` — слайд
#: остаётся **без вердикта**. Потеря покрытия, которая выглядит как молчание модели,
#: хуже медленного аудита: пропуск перестал бы отличаться от «претензий нет».
#:
#: Поэтому число поднимается осознанно — `audit.vlm_concurrency` в профиле запуска,
#: после того как на сервере поднят `--parallel` и это измерено.
DEFAULT_CONCURRENCY = 1


@dataclass(frozen=True, slots=True)
class Verdict:
    """Ответ судьи после голосования."""

    ok: bool
    confidence: float
    reason: str
    votes: int

    @property
    def is_finding(self) -> bool:
        return not self.ok


def ask(
    vlm: object,
    *,
    check_id: str,
    question: str,
    image_png: bytes,
    language: str = "ru",
    context: str = "",
    votes: int = 3,
) -> Verdict | None:
    """Вердикт модели по одному вопросу. `None` — модель не дала ни одного годного ответа.

    Первый прогон делается всегда. Если он говорит «претензий нет», на этом и
    останавливаемся: переспрашивать согласие втрое дороже и ничего не меняет — находки
    всё равно не будет. Обвинение переспрашивается: находку увидит человек, и ложная
    стоит дороже пропущенной.

    Ответ вне перечня `yes`/`no` голосом **не считается** — приём из change (5). Иначе
    сбой разбора ответа превращался бы в уверенный вердикт.
    """
    bundle = get_prompt_registry().load("audit_judge")
    system, user = bundle.render(
        check_id=check_id, question=question, language=language, context=context
    )

    collected: list[tuple[str, str]] = []
    for seed in range(max(1, votes)):
        try:
            data = vlm.ask_image(  # type: ignore[attr-defined]
                system=system,
                user=user,
                image_png=image_png,
                schema=bundle.response_schema,
                seed=seed,
            )
        except Exception:
            break

        verdict = str(data.get("verdict", "")).strip().lower()
        if verdict not in ("yes", "no"):
            continue
        collected.append((verdict, str(data.get("reason", "")).strip()))
        if seed == 0 and verdict == "yes":
            break

    if not collected:
        return None

    no_votes = [reason for verdict, reason in collected if verdict == "no"]
    ok = len(no_votes) * 2 <= len(collected)
    agreeing = len(collected) - len(no_votes) if ok else len(no_votes)
    reason = "" if ok else (no_votes[0] if no_votes else "")
    return Verdict(
        ok=ok,
        confidence=agreeing / len(collected),
        reason=reason,
        votes=len(collected),
    )


def _previews_for(ctx: CheckContext) -> dict[str, bytes]:
    previews = ctx.previews
    if not previews:
        raise CheckUnavailable("превью слайдов нет: судье нечего показать")
    if ctx.vlm is None:
        raise CheckUnavailable("VLM-клиент не передан: спросить некого")
    return previews


@dataclass(frozen=True, slots=True)
class Query:
    """Один вопрос по одному слайду: всё, что нужно, чтобы позвать судью."""

    slide_id: str
    image_png: bytes
    context: str = ""


def verdicts(
    vlm: object,
    queries: list[Query],
    *,
    check_id: str,
    question: str,
    language: str,
    votes: int,
    concurrency: int,
) -> list[tuple[Query, Verdict | None]]:
    """Вердикты по списку вопросов — **в порядке слайдов, а не ответов**.

    Порядок фиксирован намеренно: находки одного и того же аудита обязаны совпадать
    между прогонами, а `finding_id` считается от того, на что находка указывает.
    Порядок завершения потоков к содержанию отношения не имеет.

    Параллелизм бьёт по стенным часам, а не по числу вызовов: узкое место —
    ожидание ответа сервера (28 с на вызов по замеру 18.09), и на нём GIL отпущен.
    Асинхронного варианта здесь нет сознательно: `ask` синхронна снизу доверху,
    и переписывать под неё контракт проверки (`registry.py`) значило бы тронуть все
    тридцать пять проверок ради восьми.
    """
    call = partial(
        ask,
        vlm,
        check_id=check_id,
        question=question,
        language=language,
        votes=votes,
    )
    if concurrency <= 1 or len(queries) <= 1:
        return [(q, call(image_png=q.image_png, context=q.context)) for q in queries]

    with ThreadPoolExecutor(max_workers=min(concurrency, len(queries))) as pool:
        futures = [pool.submit(call, image_png=q.image_png, context=q.context) for q in queries]
        return [(q, f.result()) for q, f in zip(queries, futures, strict=True)]


def _make_check(check_id: str, question: str) -> None:
    """Регистрирует проверку-вопрос. Отдельных функций не пишем: они отличались бы
    только строкой вопроса, а расхождение между ними — источник ошибок."""

    @check(
        id=check_id,
        deterministic=False,
        severity=_SEVERITY[check_id],
        auto_fix=_AUTO_FIX.get(check_id, AutoFix.NONE),
        title=question,
    )
    def _check(ctx: CheckContext) -> Iterable[Finding]:
        previews = _previews_for(ctx)
        votes = int(ctx.param("vlm_votes", 3))
        threshold = ctx.param("vlm_confidence_threshold", 0.6)
        concurrency = max(1, int(ctx.param("vlm_concurrency", DEFAULT_CONCURRENCY)))
        language = getattr(ctx.deck, "language", None) or "ru"
        slides = list(ctx.deck.slides)

        queries: list[Query] = []
        for index, slide in enumerate(slides):
            image = previews.get(slide.slide_id)
            if image is None:
                continue

            context_text = ""
            if check_id == _PAIRWISE:
                if index == 0:
                    continue  # первому слайду не с чем соседствовать
                context_text = f"Предыдущий слайд: {slide_text(slides[index - 1])[:600]}"

            queries.append(Query(slide_id=slide.slide_id, image_png=image, context=context_text))

        asked = verdicts(
            ctx.vlm,
            queries,
            check_id=check_id,
            question=question,
            language=language,
            votes=votes,
            concurrency=concurrency,
        )
        for query, verdict in asked:
            # Модель промолчала или не уверена — это не «всё хорошо».
            # Такой слайд просто остаётся без вердикта, и находки по нему нет.
            if verdict is None or verdict.ok or verdict.confidence < threshold:
                continue

            yield make_finding(
                check_id=check_id,
                slide_id=query.slide_id,
                reason=f"verdict:{check_id}",
                message=f"{question} — нет. {verdict.reason}".strip(),
                evidence={
                    "confidence": f"{verdict.confidence:.2f}",
                    "votes": str(verdict.votes),
                    "question": question,
                },
            )


for _check_id, _question in QUESTIONS.items():
    _make_check(_check_id, _question)


#: Доля букв одной письменности, начиная с которой слайд считается набранным на ней.
#: Простое большинство не годится: «Переходим на Kubernetes и PostgreSQL» — русская
#: фраза, в которой латинских букв больше, чем кириллических.
_SCRIPT_SHARE = 0.7


def dominant_script(text: str, share: float = _SCRIPT_SHARE) -> str | None:
    """Письменность текста: `cyrillic`, `latin` или `None`, если ясного перевеса нет.

    `None` возвращается и когда букв нет вовсе, и когда ни одна письменность не набрала
    нужной доли: смесь — это ещё не смена языка, а термины и названия продуктов.
    """
    cyrillic = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    latin = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    total = cyrillic + latin
    if total == 0:
        return None
    if cyrillic / total >= share:
        return "cyrillic"
    if latin / total >= share:
        return "latin"
    return None


@check(id="content.single_language", deterministic=True, severity=Severity.WARNING,
       title="Вся колода на одном языке")
def single_language(ctx: CheckContext) -> Iterable[Finding]:
    """Вся колода на одном языке.

    Без модели: язык виден по тексту, а не по картинке, и спрашивать об этом VLM —
    двенадцать вызовов ради того, что считается сравнением двух счётчиков.

    Судим по преобладающей письменности слайда, а не по отдельным словам: названия
    продуктов, единицы и термины латиницей — норма для русской колоды, а не смена языка.
    """
    scripts: dict[str, str] = {}
    for slide in ctx.deck.slides:
        script = dominant_script(slide_text(slide))
        if script is not None:
            scripts[slide.slide_id] = script

    if len(set(scripts.values())) < 2:
        return

    # Большинство задаёт язык колоды, меньшинство — нарушители.
    counts: dict[str, int] = {}
    for script in scripts.values():
        counts[script] = counts.get(script, 0) + 1
    main = max(counts, key=lambda key: counts[key])

    for slide_id, script in scripts.items():
        if script == main:
            continue
        yield make_finding(
            check_id="content.single_language",
            slide_id=slide_id,
            reason=f"script:{script}",
            message=(
                f"Слайд набран другой письменностью ({script}), чем остальная колода ({main}): "
                "колода должна быть на одном языке"
            ),
            evidence={"script": script, "deck_script": main},
        )
