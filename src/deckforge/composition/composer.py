"""Композиция слайда: подбор макета из манифеста и распределение контента.

Change (11) `slide-composition`. Модель возвращает только валидный `SlideIR` (ADR-001).

Схема гарантирует форму, но не осмысленность: `layout_id`, которого нет в манифесте,
и `placeholder_idx`, которого нет в макете, формально валидны. Поэтому после валидации
слайд **привязывается к реальности**: макет ставится тот, что выбрало правило, чужие
плейсхолдеры и висячие ссылки выбрасываются.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from deckforge.composition.free_space import clip, effective_capacity, has_body_slot
from deckforge.composition.layout_picker import pick_layout
from deckforge.composition.visual_selector import select_chart
from deckforge.domain.base import BBox
from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import (
    Block,
    BulletsBlock,
    ChartBlock,
    ImageBlock,
    KpiBlock,
    Provenance,
    SlideIR,
    SmartArtBlock,
    TextBlock,
)
from deckforge.domain.slide import TableBlock as TableBlockIR
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import InferenceClient
from deckforge.inference.structured import generate_model
from deckforge.layout.constraints import solve_positions
from deckforge.layout.diagram import SUPPORTED_PATTERNS
from deckforge.layout.errors import LayoutFitError
from deckforge.registry import get_prompt_registry

#: Предел Приложения 1 ТЗ. Вместимость макета может быть мягче — берётся строгий.
MAX_BULLETS_BY_SPEC = 6


class CompositionError(RuntimeError):
    """Слайд собрать не удалось: от модели не осталось ни одного пригодного блока."""


#: Блоки, которые можно поставить свободно, если в макете нет подходящего плейсхолдера.
#: Текст теряться не должен: у VK WorkSpace макетов под текст нет вовсе, и раньше
#: основное содержание слайда молча исчезало.
#:
#: Схема и показатели здесь по той же причине, что и текст: это содержание слайда,
#: а не оформление. Диаграммы и таблицы в набор не входят — им нужен не просто
#: прямоугольник, а макет, который их допускает (`capacity.supports_*`).
_PLACEABLE_FREELY = (TextBlock, BulletsBlock, SmartArtBlock, KpiBlock)


class SlideComposer:
    def __init__(self, llm_client: InferenceClient, profile: str | None = None) -> None:
        self.llm = llm_client
        self.profile = profile
        #: Что композиция изменила или выбросила. Забирает узел графа в отчёт прогона.
        self.notes: list[str] = []

    async def compose(
        self,
        slide: SlidePlan,
        content: ContentPackage,
        manifest: TemplateManifest,
        variant: VariantProfile,
        seed: int,
        *,
        preserve_wording: bool = False,
        no_think: bool = False,
    ) -> SlideIR:
        """Наполняет макет содержимым слайда.

        `preserve_wording` — рычаг деградации. По умолчанию при нехватке места
        сокращается текст, а визуализация сохраняется: тип визуализации выбран под
        данные, а формулировку можно ужать без потери смысла. Если автор просил
        сохранить формулировки, жертвуется визуализация. Поля в брифе под это пока
        нет — запрос тимлиду в proposal.md.

        `no_think` добавляет в запрос «/no_think» — команду семейства Qwen3 не размышлять.
        Нужна для замера, сколько из 389 с композиции приходится на размышление.
        """
        layout = pick_layout(slide, manifest, variant)
        facts = [fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None]
        dataset = content.dataset(slide.dataset_ref) if slide.dataset_ref else None
        chart_type = select_chart(dataset) if dataset is not None else None

        # Вместимость показывается та, что слайду действительно достанется. У макета
        # без места под тело своя — ноль, и промпт просил «не более 0 знаков»: модель
        # честно отдавала один заголовок, а колода выходила без текста (#62).
        body_free = not has_body_slot(layout)

        bundle = get_prompt_registry().load("slide_composer", profile=self.profile)
        system, user = bundle.render(
            layout=layout,
            slide=slide,
            facts=facts,
            dataset=dataset,
            variant=variant.variant_id,
            seed=seed,
            size_ladder=manifest.size_ladder_pt,
            capacity=effective_capacity(layout, manifest),
            body_free=body_free,
            smartart_patterns=sorted(pattern.value for pattern in SUPPORTED_PATTERNS),
            capacity_ratio=variant.capacity_ratio(),
            language=content.brief.language,
            preserve_wording=preserve_wording,
            chart_type=chart_type.value if chart_type else None,
            no_think=no_think,
        )

        call = partial(
            generate_model,
            self.llm,
            SlideIR,
            system=system,
            user=user,
            response_schema=bundle.response_schema,
            seed=seed,
            temperature=bundle.meta.temperature,
            top_p=bundle.meta.top_p,
            max_tokens=bundle.meta.max_tokens,
            # Поля, которые проставляет `_bind`: в схеме ответа их нет (response_omit),
            # для валидации они нужны. Ошибка модели в них сжигала попытки починки.
            overrides={
                "slide_id": slide.slide_id,
                "layout_id": layout.layout_id,
                "variant": variant.variant_id,
            },
        )
        raw, _completion = await asyncio.to_thread(call)
        return self._bind(
            raw, slide, layout, manifest, variant, seed, content, chart_type, bundle.ref
        )

    def _note(self, slide_id: str, text: str) -> None:
        """Отчёт о том, что композиция изменила или выбросила.

        Молчаливая потеря — худший исход: на слайде просто нет половины содержания,
        и понять почему можно только чтением кода. Отчёт забирает узел графа.
        """
        self.notes.append(f"слайд {slide_id}: {text}")

    def _place_free(
        self,
        blocks: list[Block],
        freed: list[str],
        layout: LayoutSpec,
        manifest: TemplateManifest,
        slide_id: str,
    ) -> list[Block]:
        """Даёт координаты блокам, оставшимся без плейсхолдера.

        Решатель из слоя `layout` делит свободную часть области контента между ними
        и не даёт залезть на занятые плейсхолдеры. Плейсхолдер, выходящий за поля шаблона,
        учитывается своей видимой частью: решателю нельзя отдать рамку шире области,
        но и забыть про неё нельзя — текст встанет поверх заголовка.
        """
        content = manifest.content_bbox
        fixed: list[tuple[str, BBox | None]] = []
        for block in blocks:
            if block.block_id in freed:
                continue
            idx = getattr(block, "placeholder_idx", None)
            if idx is not None:
                placeholder = layout.placeholder(idx)
                # Занятое обрезается по области контента, а не отбрасывается целиком:
                # заголовок VK WorkSpace шире полей шаблона, проверка «целиком внутри»
                # его не видела, и свободный текст ложился прямо на него.
                box = clip(placeholder.bbox, content) if placeholder is not None else None
                if box is not None:
                    fixed.append((block.block_id, box))
            elif block.bbox is not None and (box := clip(block.bbox, content)) is not None:
                fixed.append((block.block_id, box))

        try:
            boxes = solve_positions([*fixed, *((block_id, None) for block_id in freed)], manifest)
        except LayoutFitError as error:
            self._note(slide_id, f"свободные блоки размещать некуда ({error}), они отброшены")
            return [block for block in blocks if block.block_id not in freed]

        placed: list[Block] = []
        for block in blocks:
            box = boxes.get(block.block_id) if block.block_id in freed else None
            coords = {"x": box.x, "y": box.y, "cx": box.cx, "cy": box.cy} if box else None
            placed.append(block.model_copy(update=coords) if coords else block)
        return placed

    def _bind(
        self,
        ir: SlideIR,
        slide: SlidePlan,
        layout: LayoutSpec,
        manifest: TemplateManifest,
        variant: VariantProfile,
        seed: int,
        content: ContentPackage,
        chart_type: Any,
        prompt_ref: str,
    ) -> SlideIR:
        known_placeholders = {ph.idx for ph in layout.placeholders}
        known_datasets = {d.dataset_id for d in content.datasets}
        known_assets = {a.asset_id for a in content.assets}
        max_bullets = min(MAX_BULLETS_BY_SPEC, layout.capacity.max_bullets or MAX_BULLETS_BY_SPEC)

        blocks: list[Block] = []
        freed: list[str] = []
        for block in ir.blocks:
            idx = getattr(block, "placeholder_idx", None)

            if idx is not None and idx not in known_placeholders:
                if isinstance(block, _PLACEABLE_FREELY):
                    # Текст не выбрасывается: в шаблоне может не быть ни одного макета
                    # под содержание, и тогда свободный блок в области контента —
                    # единственный способ ничего не потерять.
                    block = block.model_copy(update={"placeholder_idx": None})
                    freed.append(block.block_id)
                    self._note(
                        slide.slide_id,
                        f"блок {block.block_id}: плейсхолдера {idx} нет в макете "
                        f"{layout.layout_id}, поставлен свободным блоком",
                    )
                else:
                    self._note(
                        slide.slide_id,
                        f"блок {block.block_id} ({block.type}) отброшен: плейсхолдера "
                        f"{idx} нет в макете {layout.layout_id}",
                    )
                    continue
            elif idx is not None and isinstance(block, TextBlock) and block.color_ref is not None:
                # Цвет в плейсхолдере не задаётся: макет знает, на каком он фоне,
                # а модель — нет. Так dk1 оказывался тёмным по тёмному.
                block = block.model_copy(update={"color_ref": None})

            if isinstance(block, ChartBlock):
                if block.dataset_ref not in known_datasets:
                    self._note(
                        slide.slide_id,
                        f"диаграмма {block.block_id} отброшена: набора данных "
                        f"{block.dataset_ref} нет в контент-пакете",
                    )
                    continue
                if chart_type is not None and block.chart_type != chart_type:
                    block = block.model_copy(update={"chart_type": chart_type})
            elif isinstance(block, TableBlockIR):
                if block.dataset_ref is not None and block.dataset_ref not in known_datasets:
                    block = block.model_copy(update={"dataset_ref": None})
            elif isinstance(block, ImageBlock):
                if block.asset_ref is not None and block.asset_ref not in known_assets:
                    self._note(
                        slide.slide_id,
                        f"картинка {block.block_id} отброшена: ассета "
                        f"{block.asset_ref} нет в контент-пакете",
                    )
                    continue
            elif isinstance(block, BulletsBlock) and len(block.items) > max_bullets:
                dropped = len(block.items) - max_bullets
                block = block.model_copy(update={"items": block.items[:max_bullets]})
                self._note(
                    slide.slide_id,
                    f"буллеты {block.block_id}: {dropped} тезисов сверх предела "
                    f"{max_bullets} убрано",
                )

            # Ни плейсхолдера, ни координат — блоку просто не назвали места. Промпт
            # просит основной текст именно так, когда в макете нет места под тело:
            # координаты модель задавать не должна, их считает решатель. Проверка стоит
            # последней, чтобы более точная причина потери (нет такого датасета, нет
            # такого ассета) называлась раньше этой, общей.
            #
            # Координатам модели не доверяем вовсе: промпт их не просит, схема ответа
            # их больше не содержит, но провайдеры со своей схемой встречаются. Прогон
            # f4cf4257e07f: строгий режим требовал x, y, cx, cy, и модель клала минимум,
            # который пускала схема, — точку 0, 0, 1, 1 в углу слайда. Блок с такими
            # координатами считался размещённым, решателю не отдавался и ронял запись.
            if block.block_id not in freed and idx is None:
                if isinstance(block, _PLACEABLE_FREELY):
                    if block.bbox is not None:
                        block = block.model_copy(
                            update={"x": None, "y": None, "cx": None, "cy": None}
                        )
                    freed.append(block.block_id)
                elif block.bbox is None:
                    self._note(
                        slide.slide_id,
                        f"блок {block.block_id} ({block.type}) отброшен: ни плейсхолдера, "
                        "ни координат, а ставить его свободно нельзя",
                    )
                    continue

            blocks.append(block)

        if freed:
            blocks = self._place_free(blocks, freed, layout, manifest, slide.slide_id)

        if not blocks:
            raise CompositionError(
                f"слайд {slide.slide_id}: после отбраковки не осталось ни одного блока"
            )

        return ir.model_copy(
            update={
                "slide_id": slide.slide_id,
                "layout_id": layout.layout_id,
                "variant": variant.variant_id,
                "blocks": blocks,
                "speaker_note": ir.speaker_note or slide.speaker_note,
                "provenance": Provenance(
                    fact_refs=slide.fact_refs,
                    prompt_version=prompt_ref,
                    model=getattr(self.llm, "model", None),
                    seed=seed,
                ),
            }
        )
