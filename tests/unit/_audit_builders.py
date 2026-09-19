"""Сборка колод для тестов аудита. Change (15).

Не фикстура в `conftest.py`: тот принадлежит тимлиду, а `tests/unit/conftest.py` —
общая территория с потоками A и B, и правка там дала бы конфликт в каждом PR
(TEAMWORK.md §2). Помощник живёт отдельным модулем с подчёркиванием в имени,
чтобы pytest не принимал его за тестовый файл.

Колоды здесь собираются вокруг синтетического манифеста из `tests/conftest.py`:
макет `L01` — только заголовок, макет `L07` — заголовок и тело. Реальных шаблонов
тесты аудита не требуют: проверки работают с `SlideIR` и манифестом, а не с файлом.
"""

from __future__ import annotations

from pathlib import Path

from deckforge.audit.context import AuditContext
from deckforge.domain.content import ContentPackage
from deckforge.domain.enums import ChartType, ColorRef, ImageFit, ImageSource, TextRole
from deckforge.domain.slide import (
    Block,
    BulletItem,
    BulletsBlock,
    ChartBlock,
    DeckIR,
    ImageBlock,
    KpiBlock,
    KpiItem,
    Provenance,
    SlideIR,
    TableBlock,
    TextBlock,
)

EMU_PER_CM = 360_000

#: Совпадает с синтетическим манифестом из `tests/conftest.py`.
TEMPLATE_ID = "sha256:" + "0" * 64


def cm(value: float) -> int:
    return int(value * EMU_PER_CM)


def title(
    text: str = "Выручка выросла на треть",
    *,
    block_id: str = "b1",
    placeholder_idx: int | None = 0,
    color_ref: ColorRef | None = None,
    size_pt: float | None = None,
    box: tuple[float, float, float, float] | None = None,
) -> TextBlock:
    """Заголовок. По умолчанию ложится в плейсхолдер макета, а не в свои координаты."""
    return TextBlock(
        block_id=block_id,
        placeholder_idx=None if box else placeholder_idx,
        role=TextRole.TITLE,
        text=text,
        color_ref=color_ref,
        size_pt=size_pt,
        **_box(box),
    )


def body(
    text: str = "Основной текст слайда",
    *,
    block_id: str = "b2",
    placeholder_idx: int | None = 1,
    role: TextRole = TextRole.BODY,
    color_ref: ColorRef | None = None,
    size_pt: float | None = None,
    box: tuple[float, float, float, float] | None = None,
) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        placeholder_idx=None if box else placeholder_idx,
        role=role,
        text=text,
        color_ref=color_ref,
        size_pt=size_pt,
        **_box(box),
    )


def bullets(
    *texts: str,
    block_id: str = "b2",
    placeholder_idx: int | None = 1,
    box: tuple[float, float, float, float] | None = None,
) -> BulletsBlock:
    return BulletsBlock(
        block_id=block_id,
        placeholder_idx=None if box else placeholder_idx,
        items=[BulletItem(text=text) for text in texts],
        **_box(box),
    )


def chart(
    *,
    block_id: str = "b3",
    dataset_ref: str = "d001",
    chart_type: ChartType = ChartType.CLUSTERED_COLUMN,
    axis_titles: dict[str, str] | None = None,
    legend: bool = True,
    series_color_refs: list[ColorRef] | None = None,
    box: tuple[float, float, float, float] = (3, 6, 10, 6),
) -> ChartBlock:
    return ChartBlock(
        block_id=block_id,
        dataset_ref=dataset_ref,
        chart_type=chart_type,
        axis_titles=axis_titles if axis_titles is not None else {"value": "млн ₽"},
        legend=legend,
        series_color_refs=series_color_refs or [ColorRef.ACCENT1, ColorRef.ACCENT2],
        **_box(box),
    )


def table(
    *,
    block_id: str = "b4",
    header: list[str] | None = None,
    rows: list[list[str]] | None = None,
    box: tuple[float, float, float, float] = (3, 6, 10, 6),
) -> TableBlock:
    return TableBlock(
        block_id=block_id,
        header=header if header is not None else ["Квартал", "Выручка"],
        rows=rows if rows is not None else [["Q1", "120"], ["Q2", "150"]],
        **_box(box),
    )


def kpi(
    *,
    block_id: str = "b5",
    values: list[tuple[str, str]] | None = None,
    color_ref: ColorRef | None = None,
    box: tuple[float, float, float, float] = (3, 6, 10, 4),
) -> KpiBlock:
    pairs = values or [("37 %", "рост выручки"), ("1.2 млн", "новых пользователей")]
    return KpiBlock(
        block_id=block_id,
        items=[KpiItem(value=value, label=label, color_ref=color_ref) for value, label in pairs],
        **_box(box),
    )


def image(
    *,
    block_id: str = "b6",
    asset_ref: str = "a001",
    fit: ImageFit = ImageFit.COVER,
    box: tuple[float, float, float, float] = (3, 6, 10, 6),
) -> ImageBlock:
    return ImageBlock(
        block_id=block_id,
        source=ImageSource.ASSET,
        asset_ref=asset_ref,
        fit=fit,
        **_box(box),
    )


def slide(
    *blocks: Block,
    slide_id: str = "s01",
    layout_id: str = "L07",
    fit_report: dict[str, object] | None = None,
    fact_refs: list[str] | None = None,
) -> SlideIR:
    """Слайд колоды. `fact_refs` — то, что планировщик отдал этому слайду.

    По умолчанию их нет: большинству проверок план не нужен. Проверке
    `integrity.content_lost` он нужен — она отличает слайд без текста по замыслу
    от слайда, у которого текст потеряли, именно по фактам.
    """
    return SlideIR(
        slide_id=slide_id,
        layout_id=layout_id,
        variant="A",
        blocks=list(blocks),
        fit_report=fit_report or {},
        provenance=Provenance(fact_refs=fact_refs or []),
    )


def deck(*slides: SlideIR, deck_id: str = "deck-1", seed: int = 1337) -> DeckIR:
    return DeckIR(
        deck_id=deck_id,
        variant="A",
        template_id=TEMPLATE_ID,
        language="ru",
        seed=seed,
        slides=list(slides),
    )


def context_for(
    check_id: str,
    deck: DeckIR,
    manifest: object,
    *,
    content: ContentPackage | None = None,
    deck_path: Path | None = None,
    previews: dict[str, bytes] | None = None,
    vlm: object | None = None,
    **overrides: float | int | str | bool,
) -> AuditContext:
    """Контекст с порогами **из `configs/audit_checks.yaml`**, а не придуманными в тесте.

    Так тест заодно сторожит расхождение кода и YAML: если порог переименуют в конфиге,
    проверка молча уедет на значение по умолчанию, и тест на нарушителе это покажет.
    """
    from deckforge.registry import load_check_specs

    spec = load_check_specs().by_id(check_id)
    params: dict[str, float | int | str | bool] = dict(spec.params) if spec else {}
    params.update(overrides)
    return AuditContext(
        manifest=manifest,  # type: ignore[arg-type]
        deck=deck,
        content=content,
        previews=previews or {},
        deck_path=deck_path,
        vlm=vlm,
        params=params,
    )


def _box(box: tuple[float, float, float, float] | None) -> dict[str, int]:
    """Координаты в сантиметрах → EMU. Без них блок берёт рамку у плейсхолдера."""
    if box is None:
        return {}
    x, y, width, height = box
    return {"x": cm(x), "y": cm(y), "cx": cm(width), "cy": cm(height)}
