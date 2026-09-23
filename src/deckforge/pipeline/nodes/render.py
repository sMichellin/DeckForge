"""Узел `render`. Change (17) `pipeline-orchestration`.

Здесь колода впервые становится файлом, и здесь же снимаются превью для аудита.
Превью требуют LibreOffice, которого в образе приложения нет (он в образе воркера):
без него узел отдаёт пустой словарь и причину, а проверки, которым нечего смотреть,
сами уходят в пропущенные (change 15). Колода собирается в любом случае.
"""

from __future__ import annotations

import asyncio
import shutil
from functools import partial
from pathlib import Path

from langgraph.runtime import Runtime

from deckforge.audit.preview import (
    SofficeUnavailableError,
    render_deck_previews,
    render_layout_previews,
    render_previews,
)
from deckforge.export.pptx import export_pptx
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState

DECK_FILENAME = "deck.pptx"


#: Каталог превью слайдов-примеров внутри кэша. Разрешение то же, что у превью колоды:
#: профиль и колода обязаны мериться одной линейкой.
EXAMPLES_DIR = "example-previews"


def example_previews_of(template_path: Path, template_id: str, cache_root: Path) -> list[Path]:
    """Превью слайдов-примеров шаблона: из кэша, а нет в кэше — один рендер шаблона.

    Ключ — `template_id` (хэш файла), поэтому другой шаблон или его новая версия
    рендерятся заново, а тот же шаблон — никогда больше. Рендер пишется во временный
    каталог и переименовывается целиком: оборванный рендер не станет «готовым» кэшем.
    """
    target = cache_root / EXAMPLES_DIR / template_id.replace(":", "_")
    if target.is_dir():
        cached = sorted(target.glob("*.png"))
        if cached:
            return cached
    staging = target.with_name(target.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    render_previews(template_path, staging)
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return sorted(target.glob("*.png"))


async def render_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`DeckIR` → нативный .pptx (changes 13, 14, 21) и превью для аудита (change 6).

    Цитату и callout (DG4) рендер рисует сам — полосой и текстом по дизайн-системе (DG3);
    дизайн-система та же, что видело вписывание, — из состояния графа.
    """
    deps = runtime.context
    deck = state["deck"]
    out = deps.out_dir / DECK_FILENAME

    notes: list[str] = []
    degradations: list[str] = []
    previews: dict[str, Path] = {}
    layout_previews: dict[str, Path] = {}
    example_previews: list[Path] = []

    # Превью нужны не только судье-VLM: по картинке слайда считаются метрики оформления
    # (`design.ink_balance`), а они детерминированные и идут всегда. Рендер десяти
    # страниц стоит секунды, и без него проверка уходит в пропущенные — то есть колода
    # снова оценивается по рамкам, а не по тому, как выглядит.
    for_design = bool(deps.run.audit.get("run_deterministic", True))
    for_judge = bool(deps.run.audit.get("run_semantic", True)) and deps.vlm is not None
    wants_previews = for_design or for_judge
    # Рычаг бюджета снимает превью, только если они нужны одному судье-VLM: судья —
    # десятки минут, а рендер — секунды. Прогон d973a7ee8110 отстал от расписания,
    # простояв в очереди к модели 51 минуту, и рычаг «сэкономил» три секунды рендера —
    # ценой детерминированной проверки оформления, которая ушла в пропущенные.
    if wants_previews and not for_design and deps.budget.behind_schedule("render"):
        wants_previews = False
        degradations.append("render: превью не снимаются — остатка бюджета не хватает (§15)")

    async with timed(deps, "render") as timings:
        pptx_path = await asyncio.to_thread(
            partial(
                export_pptx,
                deck,
                state["manifest"],
                state["template_path"],
                out,
                content=state["content"],
                fonts=deps.fonts,
                design_system=state.get("design_system"),
            )
        )
        if wants_previews:
            try:
                previews = dict(
                    await asyncio.to_thread(
                        partial(render_deck_previews, pptx_path, deck, deps.previews_dir())
                    )
                )
            except (SofficeUnavailableError, OSError) as error:
                notes.append(f"превью не сняты ({error}): проверки по изображению будут пропущены")

        # Пустые макеты (C9): метрики оформления вычитают их из превью слайда, иначе
        # логотип и плашки шаблона считаются содержанием и тянут центр тяжести.
        # Без них проверка не пропускается, а считает как прежде, поэтому неудача здесь —
        # это оговорка, а не потеря проверки.
        if previews:
            try:
                layout_previews = dict(
                    await asyncio.to_thread(
                        partial(
                            render_layout_previews,
                            state["template_path"],
                            state["manifest"],
                            deps.previews_dir() / "layouts",
                            {slide.layout_id for slide in deck.slides},
                        )
                    )
                )
            # Широкий перехват намеренно: макет читает python-pptx, а пустые макеты —
            # не обязательная часть колоды. Любая их неудача обязана остаться оговоркой,
            # а не уронить рендер уже собранного файла.
            except Exception as error:
                notes.append(
                    f"превью пустых макетов не сняты ({error}): метрики оформления "
                    "посчитают декор шаблона содержанием"
                )

        # Слайды-примеры шаблона (DS7): по ним аудит строит профиль «родного» слайда.
        # Рендер примеров стоит десятки секунд (у VK Tech их 54), поэтому он делается
        # один раз на шаблон и лежит в кэше рядом с манифестами. Неудача — оговорка:
        # без профиля проверка уйдёт в пропущенные, а колода соберётся.
        manifest = state.get("manifest")
        if previews and manifest is not None and manifest.examples:
            try:
                example_previews = await asyncio.to_thread(
                    partial(
                        example_previews_of,
                        state["template_path"],
                        manifest.template_id,
                        deps.cache_dir or deps.previews_dir(),
                    )
                )
            except Exception as error:
                notes.append(
                    f"превью слайдов-примеров шаблона не сняты ({error}): "
                    "профиль оформления шаблона не построен"
                )

    return {
        "pptx_path": pptx_path,
        "previews": previews,
        "layout_previews": layout_previews,
        "example_previews": example_previews,
        "stage_timings_s": timings,
        "notes": notes,
        "degradations": degradations,
    }
