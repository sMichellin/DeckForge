"""Узел `fit`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

import asyncio

from langgraph.runtime import Runtime

from deckforge.audit.fixes.apply import shorten_to_words
from deckforge.domain.content import ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import Block, BulletsBlock, DeckIR, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fitting import SHORTEN, SPLIT, fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState

#: Сколько кругов «сократить и вписать заново», прежде чем сдаться. Каждый круг оставляет
#: 80 % слов: шесть кругов — это четверть исходного текста, дальше смысл уже не спасти.
_SHORTEN_ROUNDS = 6
_SHORTEN_KEEP = 0.8

#: Короче этого пункт или абзац не сокращается: огрызок хуже переполнения.
_MIN_WORDS = 3

#: Заголовку — два. Он не уменьшается кеглем (правило шкалы), и когда полоса заголовка
#: узкая, трёх слов со многоточием бывает много: прогон e26f1eb2b6bf упал на записи
#: из-за заголовка в 34 знака при месте на 32. Два слова хуже трёх, но лучше колоды,
#: которой нет; заметка это называет, аудит видит.
_MIN_TITLE_WORDS = 2


def _ordered(state: DeckState) -> list[SlideIR]:
    """Порядок колоды — из плана, а после витка починки — из самой колоды.

    Редьюсер состояния хранит слайды словарём по `slide_id`, а идентификаторы придумывает
    модель: сортировка строк поставила бы «s10» перед «s9». Поэтому на первом круге
    единственный источник порядка — последовательность плана.

    На витке починки план перестаёт быть полным списком: `split_slide` (change 19)
    добавляет слайд-продолжение, которого в плане нет и быть не может — его придумал
    не планировщик. Отбор по плану выбросил бы этот слайд, и починка молча теряла бы
    пункты вместо того, чтобы их разнести. После витка порядок задаёт `DeckIR`, который
    собрал `FixApplier`: он уже полный и уже упорядоченный.
    """
    deck = state.get("deck")
    if state.get("fix_round") and deck is not None:
        return list(deck.slides)

    by_id = {slide.slide_id: slide for slide in state["slides"]}
    return [by_id[s.slide_id] for s in state["plan"].slides if s.slide_id in by_id]


def _into_placeholders(slide: SlideIR) -> SlideIR:
    """Блок с плейсхолдером пишется в плейсхолдер — координаты модели рядом с ним лишние.

    Модель иногда отдаёт и то и другое. Писатель такой блок отвергает («координаты
    потерялись бы»), а вписывание меряет текст по придуманным координатам, а не по месту,
    которое отвёл шаблон. Плейсхолдер — решение автора шаблона, поэтому остаётся он.
    """
    blocks: list[Block] = []
    for block in slide.blocks:
        if getattr(block, "placeholder_idx", None) is not None and block.bbox is not None:
            block = block.model_copy(update={"x": None, "y": None, "cx": None, "cy": None})
        blocks.append(block)
    return slide.model_copy(update={"blocks": blocks})


def _shortened(block: Block) -> Block | None:
    """Блок с сокращённым на пятую часть текстом; `None`, если сокращать нечего."""

    floor = (
        _MIN_TITLE_WORDS
        if isinstance(block, TextBlock) and block.role is TextRole.TITLE
        else _MIN_WORDS
    )

    def cut(text: str) -> str:
        words = len(text.split())
        return shorten_to_words(text, max(floor, int(words * _SHORTEN_KEEP)))

    if isinstance(block, TextBlock):
        text = cut(block.text)
        return None if text == block.text else block.model_copy(update={"text": text})
    if isinstance(block, BulletsBlock):
        items = [item.model_copy(update={"text": cut(item.text)}) for item in block.items]
        if all(new.text == old.text for new, old in zip(items, block.items, strict=True)):
            return None
        return block.model_copy(update={"items": items})
    return None


def _fit_shortening(
    slide: SlideIR,
    manifest: TemplateManifest,
    fonts: FontLibrary | None,
    content: ContentPackage,
) -> tuple[SlideIR, list[str]]:
    """Вписывает слайд, сокращая текст, пока `fit_report` требует `shorten`.

    Стратегию `shorten` вписывание только назначает (LLM в слое `layout` не зовут), а писатель
    блок с переполнением не пишет. Фикс `shorten_text` есть в аудите, но аудит идёт после
    записи — до него прогон не доживал: первое же переполнение роняло стадию `render`.
    Поэтому сокращение выполняется здесь, детерминированно, и каждое попадает в заметки.

    `split` сокращается тоже, но как вынужденная мера. Делить слайд до записи некому
    (`split_slide` — фикс аудита, после записи), а блок со `split` писатель отвергает, и
    один такой блок ронял весь прогон (f4cf4257e07f: 3 слайда из 12). Сокращённый текст
    хуже разнесённого на два слайда, но лучше колоды, которой нет. Заметка это называет.
    """
    fitted = fit_slide(_into_placeholders(slide), manifest, fonts=fonts, content=content)
    touched: set[str] = set()
    wanted_split = {
        block_id
        for block_id, fit in fitted.fit_report.items()
        if fit.overflow and fit.strategy == SPLIT
    }
    for _ in range(_SHORTEN_ROUNDS):
        over = {
            block_id
            for block_id, fit in fitted.fit_report.items()
            if fit.overflow and fit.strategy in (SHORTEN, SPLIT)
        }
        blocks: list[Block] = []
        changed = False
        for block in fitted.blocks:
            shorter = _shortened(block) if block.block_id in over else None
            if shorter is not None:
                changed = True
                touched.add(block.block_id)
            blocks.append(shorter or block)
        if not changed:
            break
        fitted = fit_slide(
            fitted.model_copy(update={"blocks": blocks, "fit_report": {}}),
            manifest,
            fonts=fonts,
            content=content,
        )

    notes = [
        f"{fitted.slide_id}/{block_id}: текст сокращён, чтобы влезть"
        + (
            " (просился на два слайда — делить до записи некому)"
            if block_id in wanted_split
            else ""
        )
        + ("" if not fitted.fit_report[block_id].overflow else " — и всё равно не влез")
        for block_id in sorted(touched)
    ]
    return fitted, notes


async def fit_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Вписывание текста метриками гарнитуры до записи файла (change 12)."""
    deps = runtime.context
    manifest = state["manifest"]
    plan = state["plan"]

    def work() -> tuple[list[SlideIR], list[str], list[str]]:
        fitted: list[SlideIR] = []
        failed: list[str] = []
        notes: list[str] = []
        for slide in _ordered(state):
            try:
                slide_fitted, slide_notes = _fit_shortening(
                    slide, manifest, deps.fonts, state["content"]
                )
            except LayoutFitError as error:
                failed.append(f"слайд {slide.slide_id} не вписан: {error}")
                continue
            fitted.append(slide_fitted)
            notes.extend(slide_notes)
        return fitted, failed, notes

    async with timed(deps, "fit") as timings:
        fitted, failed, notes = await asyncio.to_thread(work)

    if not fitted:
        raise RuntimeError(f"ни один слайд не вписан: {'; '.join(failed)}")

    deck = DeckIR(
        deck_id=plan.deck_id,
        variant=state["variant"].variant_id,
        template_id=manifest.template_id,
        language=plan.language,
        seed=state["seed"],
        slides=fitted,
    )
    return {
        "deck": deck,
        "slides": fitted,
        "stage_timings_s": timings,
        "errors": failed,
        "notes": notes,
    }
