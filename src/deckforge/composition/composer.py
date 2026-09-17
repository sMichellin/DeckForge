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

from deckforge.composition.layout_picker import pick_layout
from deckforge.composition.visual_selector import select_chart
from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import BulletsBlock, ChartBlock, ImageBlock, Provenance, SlideIR
from deckforge.domain.slide import TableBlock as TableBlockIR
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import InferenceClient
from deckforge.inference.structured import generate_model
from deckforge.registry import get_prompt_registry

#: Предел Приложения 1 ТЗ. Вместимость макета может быть мягче — берётся строгий.
MAX_BULLETS_BY_SPEC = 6


class CompositionError(RuntimeError):
    """Слайд собрать не удалось: от модели не осталось ни одного пригодного блока."""


class SlideComposer:
    def __init__(self, llm_client: InferenceClient, profile: str | None = None) -> None:
        self.llm = llm_client
        self.profile = profile

    async def compose(
        self,
        slide: SlidePlan,
        content: ContentPackage,
        manifest: TemplateManifest,
        variant: VariantProfile,
        seed: int,
        *,
        preserve_wording: bool = False,
    ) -> SlideIR:
        """Наполняет макет содержимым слайда.

        `preserve_wording` — рычаг деградации. По умолчанию при нехватке места
        сокращается текст, а визуализация сохраняется: тип визуализации выбран под
        данные, а формулировку можно ужать без потери смысла. Если автор просил
        сохранить формулировки, жертвуется визуализация. Поля в брифе под это пока
        нет — запрос тимлиду в proposal.md.
        """
        layout = pick_layout(slide, manifest, variant)
        facts = [fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None]
        dataset = content.dataset(slide.dataset_ref) if slide.dataset_ref else None
        chart_type = select_chart(dataset) if dataset is not None else None

        bundle = get_prompt_registry().load("slide_composer", profile=self.profile)
        system, user = bundle.render(
            layout=layout,
            slide=slide,
            facts=facts,
            dataset=dataset,
            variant=variant.variant_id,
            seed=seed,
            size_ladder=manifest.size_ladder_pt,
            capacity=layout.capacity,
            capacity_ratio=variant.capacity_ratio(),
            language=content.brief.language,
            preserve_wording=preserve_wording,
            chart_type=chart_type.value if chart_type else None,
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
        )
        raw, _completion = await asyncio.to_thread(call)
        return self._bind(raw, slide, layout, variant, seed, content, chart_type, bundle.ref)

    def _bind(
        self,
        ir: SlideIR,
        slide: SlidePlan,
        layout: LayoutSpec,
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

        blocks = []
        for block in ir.blocks:
            idx = getattr(block, "placeholder_idx", None)
            if idx is not None and idx not in known_placeholders:
                continue
            if isinstance(block, ChartBlock):
                if block.dataset_ref not in known_datasets:
                    continue
                if chart_type is not None and block.chart_type != chart_type:
                    block = block.model_copy(update={"chart_type": chart_type})
            elif isinstance(block, TableBlockIR):
                if block.dataset_ref is not None and block.dataset_ref not in known_datasets:
                    block = block.model_copy(update={"dataset_ref": None})
            elif isinstance(block, ImageBlock):
                if block.asset_ref is not None and block.asset_ref not in known_assets:
                    continue
            elif isinstance(block, BulletsBlock) and len(block.items) > max_bullets:
                block = block.model_copy(update={"items": block.items[:max_bullets]})
            blocks.append(block)

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
