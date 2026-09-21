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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.inference.client import InferenceClient, InferenceError
from deckforge.inference.structured import generate_json
from deckforge.registry import get_prompt_registry

#: Сколько раз просить модель переписать один заголовок. Два: первый заход называет
#: предел, второй — промах в знаках. Третий сказать нечего, а вызов стоит денег и времени.
_ATTEMPTS = 2

#: Сколько вариантов заголовка просить за раз. Выбор делает измерение, а не модель:
#: чтобы промахнуться, ей теперь надо промахнуться трижды подряд. Больше трёх —
#: лишние токены: варианты начинают повторять друг друга.
_VARIANTS = 3


@dataclass(frozen=True)
class Band:
    """Полоса заголовка, под которую переписывается заголовок одного слайда.

    `fits` меряет текст так же, как потом померяет вёрстка; `limit` — предел в знаках,
    который называется модели. Мерилом служит только `fits`, предел — подсказка.
    """

    fits: Callable[[str], bool]
    limit: int


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


def _best_variant(variants: list[str], fits: Callable[[str], bool]) -> str | None:
    """Лучший из предложенных вариантов — по измерению, а не по порядку в ответе.

    Влез — значит годен, и из влезших берётся самый длинный: он содержательнее.
    Не влез ни один — берётся самый короткий: ему ближе всех до рамки, и с ним
    пойдёт второй заход.
    """
    clean = [text for text in (item.strip() for item in variants) if text]
    if not clean:
        return None
    fitting = [text for text in clean if fits(text)]
    return max(fitting, key=len) if fitting else min(clean, key=len)


def _better(candidate: str, current: str, fits: Callable[[str], bool]) -> bool:
    """Правило выбора между заходами: поместившийся бьёт непоместившийся."""
    if fits(candidate) != fits(current):
        return fits(candidate)
    return len(candidate) > len(current) if fits(candidate) else len(candidate) < len(current)


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
        band = Band(fits=fits, limit=limit)
        bands = {slide.slide_id: band for slide in plan.slides}
        return await self._rewrite(plan, content, bands, seed=seed, attempts=_ATTEMPTS)

    async def rewrite_for_layouts(
        self,
        plan: DeckPlan,
        content: ContentPackage,
        *,
        bands: Mapping[str, Band],
        seed: int,
    ) -> DeckPlan:
        """Заход под полосу макета, который слайду уже выбран (A11).

        Планировщику предел называется по медиане полос шаблона: какой макет достанется
        слайду, до `pick_layout` неизвестно. У VK Tech медиана — 63 знака, а выбранные
        макеты держат 24–32, и композиция подрезала 7 заголовков из 9. Здесь мерило
        у каждого слайда своё — полоса его макета.

        Механика та же, что у `rewrite_overlong`: одна пачка на колоду, варианты, выбор
        измерением. Вызов **один**: это уже второй заход после плана, а заголовок,
        не вставший и теперь, подрежет композиция, как и раньше. Слайд без полосы
        в `bands` не трогается: мерить его нечем.
        """
        return await self._rewrite(plan, content, bands, seed=seed, attempts=1)

    async def _rewrite(
        self,
        plan: DeckPlan,
        content: ContentPackage,
        bands: Mapping[str, Band],
        *,
        seed: int,
        attempts: int,
    ) -> DeckPlan:
        """Общая механика заходов: пачка не уместившихся, варианты, выбор измерением.

        У каждого слайда своя полоса: и мерило, и предел в промпте. Для первого захода
        после плана она у всех одна, для захода под выбранный макет — у каждого своя.
        """
        pending = [
            slide
            for slide in plan.slides
            if (band := bands.get(slide.slide_id)) is not None and not band.fits(slide.headline)
        ]
        if not pending:
            return plan

        best: dict[str, str] = {}
        why: dict[str, str] = {
            slide.slide_id: _why(slide.headline, bands[slide.slide_id].limit, None)
            for slide in pending
        }
        for attempt in range(attempts):
            fresh = await self._rewrite_batch(pending, content, bands, seed + attempt, why)
            if not fresh:
                break
            still: list[SlidePlan] = []
            for slide in pending:
                band = bands[slide.slide_id]
                variants = fresh.get(slide.slide_id) or []
                chosen = _best_variant(variants, band.fits)
                if chosen is None:
                    continue
                current = best.get(slide.slide_id)
                if current is None or _better(chosen, current, band.fits):
                    best[slide.slide_id] = chosen
                if not band.fits(chosen):
                    still.append(slide)
                    why[slide.slide_id] = _why(
                        slide.headline, band.limit, (chosen, len(chosen) - band.limit)
                    )
            pending = still
            if not pending:
                break

        slides = [
            self._accept(slide, best, band.fits)
            if (band := bands.get(slide.slide_id)) is not None
            else slide
            for slide in plan.slides
        ]
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
        bands: Mapping[str, Band],
        seed: int,
        why: dict[str, str],
    ) -> dict[str, list[str]]:
        """Варианты заголовков всей пачки за один вызов. Пустой словарь — модель молчит.

        Модель может вернуть не все слайды или придумать чужой `slide_id`: лишнее
        отбрасывается, недостающие остаются с прежним заголовком. Ронять из-за этого
        прогон нельзя — колода соберётся и с подрезанным заголовком.
        """
        bundle = get_prompt_registry().load("headline_writer", profile=self.profile)
        items = [
            {
                "slide_id": slide.slide_id,
                "headline": slide.headline,
                "limit": bands[slide.slide_id].limit,
                "why": why[slide.slide_id],
                "facts": [
                    fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None
                ],
            }
            for slide in slides
        ]
        system, user = bundle.render(
            items=items, language=content.brief.language, variants=_VARIANTS
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
        out: dict[str, list[str]] = {}
        for row in data.get("headlines") or []:
            if not isinstance(row, dict):
                continue
            slide_id = str(row.get("slide_id") or "")
            if slide_id not in known:
                continue
            # Модель может вернуть и список вариантов (1.2.0), и одну строку (1.1.0):
            # разбирать оба вида дешевле, чем падать из-за версии промпта в профиле.
            raw = row.get("variants")
            variants = raw if isinstance(raw, list) else [row.get("headline")]
            texts = [str(item).strip() for item in variants if str(item or "").strip()]
            if texts:
                out[slide_id] = texts
        return out

    def _note(self, slide_id: str, text: str) -> None:
        self.notes.append(f"слайд {slide_id}: {text}")
