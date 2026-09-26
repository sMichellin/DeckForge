"""Состояние графа. Change (17) `pipeline-orchestration`.

В состоянии живут только модели и пути: оно целиком уезжает в чекпойнт sqlite
и читается интерфейсом. Модели — доменные и производные от них (`designsystem`);
и те и другие — pydantic, то есть переживают сериализацию чекпойнта.
Клиенты инференса, судья и каталог шрифтов ходят мимо него — через `Deps`
(см. `pipeline/deps.py`).

Превью держатся **путями, а не байтами**: колода на 12 слайдов — это мегабайты png,
и чекпойнт, который пишется после каждого узла, вырос бы на них в десятки раз.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, TypedDict

from deckforge.designsystem import DesignSystem
from deckforge.domain.audit import AuditReport, Finding
from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan
from deckforge.domain.slide import DeckIR, SlideIR
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile


def _merge_slides(left: list[SlideIR], right: list[SlideIR]) -> list[SlideIR]:
    """Редьюсер композиции и витка фиксов: слайд с тем же `slide_id` замещает прежний.

    Порядок колоды берётся из плана (`nodes/fit.py`), а не из сортировки по `slide_id`:
    идентификаторы придумывает модель, и «s9» против «s10» сортировкой даёт неверный
    порядок слайдов.
    """
    by_id = {s.slide_id: s for s in left}
    by_id.update({s.slide_id: s for s in right})
    return list(by_id.values())


def _append(left: list[str], right: list[str]) -> list[str]:
    """Сообщения копятся: узел дописывает, а не затирает чужие."""
    return [*left, *right]


def _merge_timings(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    """`parse_template` и `ingest_content` идут параллельно и пишут тайминги разом."""
    return {**left, **right}


class DeckState(TypedDict, total=False):
    run_id: str
    seed: int
    template_path: Path
    content_paths: list[Path]

    manifest: TemplateManifest
    #: Производные шаблона: роли цветов, контрасты, лестница типографики, шкала
    #: отступов, компоненты. Считается из манифеста тем же узлом `parse` (DG2) —
    #: не кэшируется отдельно, потому что кэшируется её единственный источник.
    design_system: DesignSystem
    content: ContentPackage
    variant: VariantProfile

    plan: DeckPlan
    #: Сколько слайдов и почему: режим (`exact` / `auto`), заданное, подобранное,
    #: сколько дал план, причина словами (Т1). Показывает интерфейс.
    slides_decision: dict[str, Any]
    slides: Annotated[list[SlideIR], _merge_slides]
    deck: DeckIR

    pptx_path: Path
    #: `slide_id` → путь к png. Пусто, если LibreOffice недоступен.
    previews: dict[str, Path]
    #: `layout_id` → путь к png пустого макета: оформление шаблона без содержания (C9).
    layout_previews: dict[str, Path]
    #: Превью слайдов-примеров шаблона, из кэша по `template_id` (DS7).
    example_previews: list[Path]
    #: `slide_id` → метрики оформления слайда (C7). Есть у каждого слайда, а не только
    #: у нарушителей: иначе колоды между прогонами не сравнить.
    design_metrics: dict[str, dict[str, float]]
    audit: AuditReport

    selected_fixes: list[Finding]
    fix_round: int
    #: Отличает применённый фикс от пропущенного: без этого виток починки, которому
    #: нечем чинить, крутился бы до предела витков вхолостую.
    fix_applied: bool
    exports: dict[str, Path]

    stage_timings_s: Annotated[dict[str, float], _merge_timings]
    #: Что не отработало: слайд не собрался, pdf не получился, фиксов ещё нет.
    errors: Annotated[list[str], _append]
    #: Что сделано не по основному пути: пропуски и оговорки без потери качества.
    notes: Annotated[list[str], _append]
    #: Сработавшие рычаги §15 — какое качество и на чём разменяно.
    degradations: Annotated[list[str], _append]
    #: Проверки аудита, которым нечего было смотреть (change 15).
    skipped_checks: list[str]
