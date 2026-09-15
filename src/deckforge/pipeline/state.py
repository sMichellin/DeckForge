"""Состояние графа. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, TypedDict

from deckforge.domain.audit import AuditReport, Finding
from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan
from deckforge.domain.slide import DeckIR, SlideIR
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile


def _merge_slides(left: list[SlideIR], right: list[SlideIR]) -> list[SlideIR]:
    """Редьюсер для параллельной композиции: слайды приходят из разных веток."""
    by_id = {s.slide_id: s for s in left}
    by_id.update({s.slide_id: s for s in right})
    return sorted(by_id.values(), key=lambda s: s.slide_id)


class DeckState(TypedDict, total=False):
    run_id: str
    seed: int
    template_path: Path
    content_paths: list[Path]

    manifest: TemplateManifest
    content: ContentPackage
    variant: VariantProfile

    plan: DeckPlan
    slides: Annotated[list[SlideIR], _merge_slides]
    deck: DeckIR

    pptx_path: Path
    previews: dict[str, bytes]
    audit: AuditReport

    selected_fixes: list[Finding]
    fix_round: int
    exports: dict[str, Path]

    stage_timings_s: dict[str, float]
    errors: list[str]
