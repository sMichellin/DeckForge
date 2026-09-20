"""Переписывание заголовков, которые не уместились в полосу макета.

Правка change (10) `deck-planning`. Предел длины заголовка модели названа (правило 4
промпта планировщика), но она его не держит: прогон `ea732e59510c` — 9 заголовков из 10
длиннее места. Дальше их резала композиция, и вывод превращался в обрубок с многоточием:
«Существующие AI-инструменты не решают…» не говорит, чего они не решают.

Переписать заголовок короче, сохранив вывод, может только модель — код умеет лишь
выбрасывать слова. Поэтому здесь не сокращение, а второй, дешёвый вызов (`llm_fast`).

**Мерило сюда не импортируется.** Помещается заголовок или нет, знает слой вёрстки,
а `planning` его не импортирует (правило 1 AGENTS.md): измерение приходит функцией
`fits` от узла графа. Этот слой решает, что делать с ответом, и не знает про рамки.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial

from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.inference.client import InferenceClient, InferenceError
from deckforge.inference.structured import generate_json
from deckforge.registry import get_prompt_registry

#: Сколько раз просить модель переписать один заголовок. Два: первый заход называет
#: предел, второй — промах в знаках. Третий сказать нечего, а вызов стоит денег и времени.
_ATTEMPTS = 2


def _why(headline: str, limit: int, miss: tuple[str, int] | None) -> str:
    """Что сказать модели о заголовке: в первый раз — предел, во второй — промах."""
    if miss is None:
        return f"не помещается в полосу заголовка: {len(headline)} знаков при пределе {limit}"
    previous, over = miss
    return (
        f"твой прошлый вариант «{previous}» тоже не поместился — он на {over} знаков "
        f"длиннее места. Нужно уложиться в {limit} знаков: выбрось подробность, "
        "а не сказуемое"
    )


class HeadlineRewriter:
    """Второй заход по заголовкам плана: не уместившиеся пишутся заново."""

    def __init__(self, llm_client: InferenceClient, profile: str | None = None) -> None:
        self.llm = llm_client
        self.profile = profile
        #: Что сделано с каждым не уместившимся заголовком. Забирает узел графа в отчёт.
        self.notes: list[str] = []

    async def rewrite_overlong(
        self,
        plan: DeckPlan,
        content: ContentPackage,
        *,
        fits: Callable[[str], bool],
        limit: int,
        seed: int,
        slots: asyncio.Semaphore | None = None,
    ) -> DeckPlan:
        """План с заголовками, которые помещаются, — насколько модель смогла.

        `fits` меряет текст так же, как потом померяет вёрстка. `limit` — тот же предел
        в знаках, что назван планировщику: он уезжает в промпт, мерилом не служит.

        До двух заходов на заголовок, и только на те, что не уместились: на прогоне
        `34272d11db06` это шесть вызовов дешёвой модели вместо десяти.
        """
        overlong = [slide for slide in plan.slides if not fits(slide.headline)]
        if not overlong:
            return plan

        gate = slots or asyncio.Semaphore(len(overlong))

        async def one(slide: SlidePlan) -> tuple[str, str | None]:
            async with gate:
                return slide.slide_id, await self._best(slide, content, fits, limit, seed)

        rewritten = dict(await asyncio.gather(*(one(slide) for slide in overlong)))

        slides = [self._accept(slide, rewritten, fits) for slide in plan.slides]
        return plan.model_copy(update={"slides": slides})

    async def _best(
        self,
        slide: SlidePlan,
        content: ContentPackage,
        fits: Callable[[str], bool],
        limit: int,
        seed: int,
    ) -> str | None:
        """Лучший вариант заголовка за отведённые заходы.

        Второй заход отличается от первого не настойчивостью, а сведениями: модели
        называется промах в знаках — «твой вариант на 6 длиннее места». Повторить
        ту же просьбу теми же словами значит получить тот же ответ (прогон 34272d11db06:
        шесть заголовков из десяти не уместились и после первого захода).
        """
        best: str | None = None
        miss: tuple[str, int] | None = None
        for attempt in range(_ATTEMPTS):
            fresh = await self._rewrite(slide, content, limit, seed + attempt, miss)
            if fresh is None:
                break
            if best is None or len(fresh) < len(best):
                best = fresh
            if fits(fresh):
                return fresh
            miss = (fresh, len(fresh) - limit)
        return best

    def _accept(
        self,
        slide: SlidePlan,
        rewritten: dict[str, str | None],
        fits: Callable[[str], bool],
    ) -> SlidePlan:
        """Брать ли переписанный заголовок вместо исходного.

        Короче — значит лучше, даже если всё ещё длинно: композиции останется выбросить
        меньше слов. Не короче — значит модель не справилась, и менять один длинный
        заголовок на другой длинный незачем: исходный хотя бы написан по материалам.
        """
        if slide.slide_id not in rewritten:
            return slide

        fresh = rewritten[slide.slide_id]
        was = len(slide.headline)
        if fresh is None:
            return slide  # причину уже назвал `_rewrite`
        if fits(fresh):
            self._note(slide.slide_id, f"заголовок переписан под рамку: {was} → {len(fresh)}")
            return slide.model_copy(update={"headline": fresh})
        if len(fresh) < was:
            self._note(
                slide.slide_id,
                f"заголовок переписан короче ({was} → {len(fresh)}), но в рамку "
                "всё равно не встал — остаток подрежет композиция",
            )
            return slide.model_copy(update={"headline": fresh})

        self._note(
            slide.slide_id,
            f"переписанный заголовок не короче исходного ({was} знаков) — оставлен исходный",
        )
        return slide

    async def _rewrite(
        self,
        slide: SlidePlan,
        content: ContentPackage,
        limit: int,
        seed: int,
        miss: tuple[str, int] | None = None,
    ) -> str | None:
        """Один заголовок заново. `None` — модель не ответила; это не повод ронять прогон.

        `miss` — предыдущий вариант и насколько он оказался длиннее места.
        """
        facts = [fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None]
        bundle = get_prompt_registry().load("headline_writer", profile=self.profile)
        system, user = bundle.render(
            max_chars=limit,
            language=content.brief.language,
            current_headline=slide.headline,
            finding_message=_why(slide.headline, limit, miss),
            slide_text=slide.speaker_note or "",
            facts=facts,
        )
        call = partial(
            generate_json,
            self.llm,
            system=system,
            user=user,
            response_schema=bundle.response_schema,
            seed=seed,
            temperature=bundle.meta.temperature,
            top_p=bundle.meta.top_p,
            max_tokens=bundle.meta.max_tokens,
            schema_name="Headline",
            skill_ref=bundle.ref,
        )
        try:
            data, _completion = await asyncio.to_thread(call)
        except InferenceError as error:
            # Заголовок, который не уместился, — не отказ прогона: колода соберётся
            # и с подрезанным. Причина уезжает в отчёт, а не в трейсбек.
            self._note(slide.slide_id, f"модель не переписала заголовок: {error}")
            return None
        headline = str(data.get("headline") or "").strip()
        if not headline:
            self._note(slide.slide_id, "модель вернула пустой заголовок — оставлен исходный")
            return None
        return headline

    def _note(self, slide_id: str, text: str) -> None:
        self.notes.append(f"слайд {slide_id}: {text}")
