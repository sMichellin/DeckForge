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

        Заходов два и вызовов два: вся колода уходит одним запросом, второй заход —
        тоже одним, для тех, кто не уместился. По вызову на заголовок стоило 130 с
        стадии `plan` на однослотовом сервере (прогон e6e1f2283ca8).

        `slots` не используется: вызов один, и делить нечего. Параметр остаётся ради
        вызывающего — узел графа отдаёт ограничитель всем, кто ходит к модели.
        """
        _ = slots
        pending = [slide for slide in plan.slides if not fits(slide.headline)]
        if not pending:
            return plan

        best: dict[str, str] = {}
        why: dict[str, str] = {
            slide.slide_id: _why(slide.headline, limit, None) for slide in pending
        }
        for attempt in range(_ATTEMPTS):
            fresh = await self._rewrite_batch(pending, content, limit, seed + attempt, why)
            if not fresh:
                break
            still: list[SlidePlan] = []
            for slide in pending:
                candidate = fresh.get(slide.slide_id)
                if candidate is None:
                    continue
                current = best.get(slide.slide_id)
                if current is None or len(candidate) < len(current):
                    best[slide.slide_id] = candidate
                if not fits(candidate):
                    still.append(slide)
                    why[slide.slide_id] = _why(
                        slide.headline, limit, (candidate, len(candidate) - limit)
                    )
            pending = still
            if not pending:
                break

        slides = [self._accept(slide, best, fits) for slide in plan.slides]
        return plan.model_copy(update={"slides": slides})

    def _accept(
        self,
        slide: SlidePlan,
        rewritten: dict[str, str],
        fits: Callable[[str], bool],
    ) -> SlidePlan:
        """Брать ли переписанный заголовок вместо исходного.

        Короче — значит лучше, даже если всё ещё длинно: композиции останется выбросить
        меньше слов. Не короче — значит модель не справилась, и менять один длинный
        заголовок на другой длинный незачем: исходный хотя бы написан по материалам.
        """
        fresh = rewritten.get(slide.slide_id)
        if fresh is None:
            return slide
        was = len(slide.headline)
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

    async def _rewrite_batch(
        self,
        slides: list[SlidePlan],
        content: ContentPackage,
        limit: int,
        seed: int,
        why: dict[str, str],
    ) -> dict[str, str]:
        """Заголовки всей пачки за один вызов. Пустой словарь — модель не ответила.

        Модель может вернуть не все слайды или придумать чужой `slide_id`: лишнее
        отбрасывается, недостающие остаются с прежним заголовком. Ронять из-за этого
        прогон нельзя — колода соберётся и с подрезанным заголовком.
        """
        bundle = get_prompt_registry().load("headline_writer", profile=self.profile)
        items = [
            {
                "slide_id": slide.slide_id,
                "headline": slide.headline,
                "limit": limit,
                "why": why[slide.slide_id],
                "facts": [
                    fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None
                ],
            }
            for slide in slides
        ]
        system, user = bundle.render(items=items, language=content.brief.language)
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
            schema_name="Headlines",
            skill_ref=bundle.ref,
        )
        try:
            data, _completion = await asyncio.to_thread(call)
        except InferenceError as error:
            # Заголовок, который не уместился, — не отказ прогона: колода соберётся
            # и с подрезанным. Причина уезжает в отчёт, а не в трейсбек.
            self.notes.append(f"заголовки переписать не удалось: {error}")
            return {}

        known = {slide.slide_id for slide in slides}
        out: dict[str, str] = {}
        for row in data.get("headlines") or []:
            if not isinstance(row, dict):
                continue
            slide_id = str(row.get("slide_id") or "")
            headline = str(row.get("headline") or "").strip()
            if slide_id in known and headline:
                out[slide_id] = headline
        return out

    def _note(self, slide_id: str, text: str) -> None:
        self.notes.append(f"слайд {slide_id}: {text}")
