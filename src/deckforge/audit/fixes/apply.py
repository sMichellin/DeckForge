"""Применение выбранных пользователем фиксов к `DeckIR`. Change (19) `audit-remediation`.

Три свойства, ради которых слой написан именно так.

**Фикс никогда не применяется молча.** Каждая находка возвращается с проставленным
`auto_fix_applied` и строкой в `evidence`: `fix` — что сделано, `fix_skipped` — почему
не сделано. Пользователь выбрал починку и обязан увидеть её результат, включая отказ;
молчаливое «применили, что смогли» превращает выбор в лотерею.

**Починка не изобретает значений.** Кегль берётся ступенью ниже по шкале шаблона,
координата — по направляющей манифеста, цвет — из акцентов темы (ADR-002). Своих чисел
у этого слоя нет вовсе: он умеет только выбирать из того, что предложил шаблон.

**Отказ от фикса — не ошибка.** Шкала кончилась, направляющая дальше допуска, заголовок
переписывает модель — всё это законные исходы. Они отличаются от успеха флагом, а не
исключением: виток починки не должен падать из-за того, что одну находку чинить нечем.

Отчёт, который возвращает `apply`, — **журнал витка, а не результат аудита**. Ни одна
проверка здесь не запускается: перепроверка идёт следующим кругом графа, после
вписывания и записи файла (`pipeline/nodes/fix.py`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from deckforge.audit.geometry import FULL_BLEED_SHARE, covers, positioned_blocks
from deckforge.domain.audit import AuditReport, AuditSummary, Finding
from deckforge.domain.base import BBox, DomainModel
from deckforge.domain.enums import AutoFix, ColorRef, Severity, TextRole
from deckforge.domain.rules import delta_e_rgb, next_size_down, snap_to_nearest
from deckforge.domain.slide import (
    Block,
    BulletItem,
    BulletsBlock,
    ChartBlock,
    DeckIR,
    SlideIR,
    TextBlock,
)
from deckforge.domain.template import TemplateManifest
from deckforge.domain.units import emu_to_cm
from deckforge.registry import CheckRegistryFile, load_check_specs

#: Цвета серий берутся только из акцентов: `dk*`/`lt*` — цвета текста и фона, и серия,
#: перекрашенная в цвет фона, исчезает с диаграммы вместо того, чтобы отличаться.
SERIES_PALETTE: tuple[ColorRef, ...] = (
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
)

#: Границы, по которым разрешено резать длинный пункт: на них мысль заканчивается.
CLAUSE_ENDINGS = (",", ";", ":", "—", "–", "-")

_CONTINUATION: dict[str, str] = {"ru": "(продолжение)", "en": "(continued)"}


@dataclass(frozen=True, slots=True)
class Outcome:
    """Исход одной починки: применена или нет и почему."""

    applied: bool
    note: str


class FixApplier:
    """Применяет выбранные находки к колоде и отчитывается, что именно сделано."""

    def __init__(self, specs: CheckRegistryFile | None = None) -> None:
        # Пороги берутся из того же `configs/audit_checks.yaml`, что и у проверок.
        # Иначе «слишком длинный» у проверки и у починки разошлись бы, и фикс оставлял
        # бы пункт ровно таким, на какой проверка снова ругается.
        self._specs = specs or load_check_specs()

    def apply(
        self,
        deck: DeckIR,
        findings: list[Finding],
        manifest: TemplateManifest,
    ) -> tuple[DeckIR, AuditReport]:
        """Возвращает обновлённую колоду и журнал витка с флагом у каждой находки."""
        started = time.perf_counter()
        slides = list(deck.slides)
        handled: list[Finding] = []

        for finding in sorted(findings, key=_order):
            slides, outcome = self._dispatch(finding, slides, manifest, deck.language)
            handled.append(_record(finding, outcome))

        fixed = _replace(deck, slides=slides)
        return fixed, AuditReport(
            deck_id=deck.deck_id,
            variant=deck.variant,
            findings=handled,
            # `passed` остаётся нулём: витку нечего засчитывать пройденным — он ничего
            # не проверял. Счёт применённого виден по `auto_fix_applied` в находках.
            summary=AuditSummary(
                errors=sum(1 for f in handled if f.severity is Severity.ERROR),
                warnings=sum(1 for f in handled if f.severity is Severity.WARNING),
                infos=sum(1 for f in handled if f.severity is Severity.INFO),
                passed=0,
            ),
            duration_s=round(time.perf_counter() - started, 3),
        )

    # --- маршрутизация -------------------------------------------------------

    def _dispatch(
        self,
        finding: Finding,
        slides: list[SlideIR],
        manifest: TemplateManifest,
        language: str,
    ) -> tuple[list[SlideIR], Outcome]:
        index = next((i for i, s in enumerate(slides) if s.slide_id == finding.slide_id), None)
        if index is None:
            return slides, Outcome(False, "слайда с таким slide_id в колоде нет")

        if finding.auto_fix is AutoFix.SPLIT_SLIDE:
            return self._split_slide(slides, index, language)

        if finding.auto_fix is AutoFix.REGENERATE_HEADLINE:
            # Осознанная граница, а не недоделка: заголовок пишет модель, а у слоя
            # фиксов нет ни клиента инференса, ни контент-пакета с фактами. Дать ему
            # их значило бы протащить композицию внутрь аудита (ARCHITECTURE.md §3).
            return slides, Outcome(False, "заголовок переписывает модель — это работа композиции")

        if finding.auto_fix is AutoFix.NONE:
            return slides, Outcome(False, "у находки не объявлен авто-фикс")

        slide = slides[index]
        block = slide.block(finding.block_id) if finding.block_id else None
        if block is None:
            return slides, Outcome(False, "блока с таким block_id на слайде нет")

        if finding.auto_fix is AutoFix.SHRINK_FONT:
            slide, outcome = self._shrink_font(slide, block, manifest)
        elif finding.auto_fix is AutoFix.SNAP_TO_GUIDE:
            slide, outcome = self._snap_to_guide(slide, block, finding, manifest)
        elif finding.auto_fix is AutoFix.SHORTEN_TEXT:
            slide, outcome = self._shorten_text(slide, block, finding)
        elif finding.auto_fix is AutoFix.MAP_TO_NEAREST_THEME_COLOR:
            slide, outcome = self._recolor(slide, block, finding, manifest)
        else:  # pragma: no cover — перечисление закрыто, ветка на случай нового значения
            return slides, Outcome(False, f"фикс {finding.auto_fix} не реализован")

        if outcome.applied:
            slides = [*slides[:index], slide, *slides[index + 1 :]]
        return slides, outcome

    # --- сами фиксы ----------------------------------------------------------

    def _shrink_font(
        self, slide: SlideIR, block: Block, manifest: TemplateManifest
    ) -> tuple[SlideIR, Outcome]:
        """`shrink_font`: следующая ступень вниз по шкале шаблона."""
        if not isinstance(block, TextBlock | BulletsBlock):
            return slide, Outcome(False, "кегль есть только у текста и буллетов")

        step = manifest.typography(block.role)
        current = block.size_pt or (step.size_pt if step else None)
        if current is None:
            return slide, Outcome(False, f"роли {block.role} нет в шкале шаблона")

        smaller = next_size_down(manifest, current)
        if smaller is None:
            return slide, Outcome(
                False, f"{current:g} pt — последняя ступень шкалы, уменьшать не на что"
            )

        # Замер вписывания устарел вместе с кеглем. Оставить его значит показать
        # пользователю переполнение, которого на новом кегле может уже не быть:
        # `layout.text_overflow` верит `fit_report` охотнее, чем собственной оценке.
        return (
            _replace(
                slide,
                blocks=_with_block(slide, _replace(block, size_pt=smaller)),
                fit_report=_without(slide.fit_report, block.block_id),
            ),
            Outcome(True, f"кегль {current:g} → {smaller:g} pt"),
        )

    def _snap_to_guide(
        self, slide: SlideIR, block: Block, finding: Finding, manifest: TemplateManifest
    ) -> tuple[SlideIR, Outcome]:
        """`snap_to_guide`: дотянуть координату до направляющей манифеста."""
        axis = finding.evidence.get("axis")
        if axis not in ("x", "y"):
            return slide, Outcome(False, "в находке не указана ось")

        value = block.x if axis == "x" else block.y
        if value is None:
            return slide, Outcome(False, "блок стоит в плейсхолдере: его положение выбрал шаблон")

        guides = manifest.grid.guides_x_emu if axis == "x" else manifest.grid.guides_y_emu
        tolerance = int(self._param("layout.off_guides", "tolerance_emu", 0))
        snapped = snap_to_nearest(value, guides, tolerance)
        if snapped == value:
            return slide, Outcome(False, "ближайшая направляющая дальше допуска")

        # Починка обязана оставить колоду записываемой. Направляющая может оказаться
        # такой, что блок вылезет за поля, и писатель отвергнет уже собранный файл:
        # прогон 80e7af41ab54 упал на витке починки, сдвинув три блока на 0,12 см вниз.
        moved = _replace(block, **{axis: snapped})
        box = moved.bbox
        if box is not None and not manifest.content_bbox.contains(box):
            return slide, Outcome(
                False,
                f"направляющая вывела бы блок за поля шаблона "
                f"({emu_to_cm(value):.2f} → {emu_to_cm(snapped):.2f} см)",
            )

        # Рамка соседа — такая же граница, как поле шаблона. Направляющие шаблона
        # проходят и там, где стоит заголовок: у VK Tech направляющая на 1,98 см
        # против рамок заголовков до 2,08 см, и подтяжка затаскивала свободный блок
        # под заголовок (прогон 5507bff9e589, слайды 4 и 9). Выравнивание —
        # предупреждение, наложение — ошибка: менять первое на второе починка не вправе.
        if box is not None and (neighbour := _climbed_onto(slide, block, box, manifest)):
            return slide, Outcome(
                False,
                f"направляющая положила бы блок на {neighbour} "
                f"({emu_to_cm(value):.2f} → {emu_to_cm(snapped):.2f} см)",
            )

        return (
            _replace(slide, blocks=_with_block(slide, moved)),
            Outcome(True, f"{axis}: {emu_to_cm(value):.2f} → {emu_to_cm(snapped):.2f} см"),
        )

    def _shorten_text(
        self, slide: SlideIR, block: Block, finding: Finding
    ) -> tuple[SlideIR, Outcome]:
        """`shorten_text`: обрезать длинный пункт по границе мысли."""
        if not isinstance(block, BulletsBlock):
            return slide, Outcome(False, "сокращать по словам умеем только буллеты")

        position = _int_or_none(finding.evidence.get("item_index"))
        if position is None or not 0 <= position < len(block.items):
            return slide, Outcome(False, "в находке не указан номер пункта")

        limit = int(self._param("density.bullet_too_long", "max_words", 15))
        item = block.items[position]
        shortened = shorten_to_words(item.text, limit)
        if shortened == item.text:
            return slide, Outcome(False, "пункт уже не длиннее допустимого")

        items = [
            _replace(it, text=shortened) if i == position else it
            for i, it in enumerate(block.items)
        ]
        was, now = len(item.text.split()), len(shortened.split())
        return (
            _replace(
                slide,
                blocks=_with_block(slide, _replace(block, items=items)),
                fit_report=_without(slide.fit_report, block.block_id),
            ),
            Outcome(True, f"пункт {position + 1}: {was} → {now} слов"),
        )

    def _recolor(
        self, slide: SlideIR, block: Block, finding: Finding, manifest: TemplateManifest
    ) -> tuple[SlideIR, Outcome]:
        """`map_to_nearest_theme_color`: развести серии, слившиеся в один цвет."""
        if finding.evidence.get("color_ref"):
            # Находка про слот вне палитры. В IR он невыразим: `ColorRef` перечисляет
            # ровно те двенадцать имён, что обязаны быть в теме, а `ThemeColors`
            # не допускает отсутствия ни одного. Чинить нечего — и подменять цвет,
            # которого нет, значит выдумывать.
            return slide, Outcome(False, "слот вне палитры в IR невыразим: чинить нечего")

        if not isinstance(block, ChartBlock):
            return slide, Outcome(False, "повтор цвета серий бывает только у диаграммы")

        taken: set[ColorRef] = set()
        updated: list[ColorRef] = []
        changes: list[str] = []
        for ref in block.series_color_refs:
            if ref not in taken:
                taken.add(ref)
                updated.append(ref)
                continue
            candidate = most_distant(manifest, taken)
            if candidate is None:
                updated.append(ref)
                continue
            taken.add(candidate)
            updated.append(candidate)
            changes.append(f"{ref.value} → {candidate.value}")

        if not changes:
            return slide, Outcome(False, "свободных акцентов в теме не осталось")

        return (
            _replace(slide, blocks=_with_block(slide, _replace(block, series_color_refs=updated))),
            Outcome(True, "серии разведены: " + ", ".join(changes)),
        )

    def _split_slide(
        self, slides: list[SlideIR], index: int, language: str
    ) -> tuple[list[SlideIR], Outcome]:
        """`split_slide`: пункты сверх лимита уезжают на слайд-продолжение."""
        slide = slides[index]
        limit = int(self._param("density.too_many_bullets", "max_bullets", 6))
        bullets = [b for b in slide.blocks if isinstance(b, BulletsBlock)]
        total = sum(len(b.items) for b in bullets)
        if not bullets or total <= limit:
            return slides, Outcome(False, "пунктов уже не больше допустимого")

        budget = limit
        head: dict[str, list[BulletItem]] = {}
        tail: dict[str, list[BulletItem]] = {}
        for block in bullets:
            take = min(budget, len(block.items))
            head[block.block_id] = list(block.items[:take])
            tail[block.block_id] = list(block.items[take:])
            budget -= take

        # Блок без единого пункта в IR невыразим (`items` min_length=1), поэтому
        # опустевший блок не остаётся пустым, а исчезает со своей половины.
        kept = [
            _replace(b, items=head[b.block_id]) if isinstance(b, BulletsBlock) else b
            for b in slide.blocks
            if not isinstance(b, BulletsBlock) or head[b.block_id]
        ]
        moved = [_replace(b, items=tail[b.block_id]) for b in bullets if tail[b.block_id]]
        if not moved:
            return slides, Outcome(False, "переносить нечего")

        title = next(
            (b for b in slide.blocks if isinstance(b, TextBlock) and b.role is TextRole.TITLE),
            None,
        )
        carried: list[Block] = []
        if title is not None:
            # Тот же заголовок дважды подряд читается как сбой генерации, поэтому
            # продолжение помечается словом. Переписать заголовок по смыслу — работа
            # модели, а не этого слоя (см. `regenerate_headline`).
            carried.append(_replace(title, text=f"{title.text} {_continuation_mark(language)}"))

        continuation = SlideIR(
            slide_id=_free_slide_id(slides, slide.slide_id),
            layout_id=slide.layout_id,
            variant=slide.variant,
            blocks=[*carried, *moved],
            speaker_note=slide.speaker_note,
            provenance=slide.provenance,
            # `fit_report` пуст намеренно: продолжение ещё не вписывали.
        )
        trimmed = _replace(
            slide,
            blocks=kept,
            fit_report={k: v for k, v in slide.fit_report.items() if not tail.get(k)},
        )
        return (
            [*slides[:index], trimmed, continuation, *slides[index + 1 :]],
            Outcome(
                True,
                f"{total} пунктов разделены: {limit} осталось, "
                f"{total - limit} уехали на слайд {continuation.slide_id}",
            ),
        )

    def _param(self, check_id: str, name: str, default: float) -> float:
        spec = self._specs.by_id(check_id)
        value = spec.params.get(name) if spec is not None else None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return default
        return float(value)


# --- свободные функции -------------------------------------------------------


def shorten_to_words(text: str, limit: int) -> str:
    """Сокращает текст до `limit` слов, по возможности — по границе мысли.

    Обрыв посреди придаточного («выручка выросла на 37 процентов, что выше…») читается
    как брак, поэтому сначала ищется запятая или тире внутри лимита: по ним фраза
    заканчивается сама и многоточие не нужно. Граница ближе половины лимита не годится —
    от пункта остался бы огрызок.
    """
    words = text.split()
    if limit <= 0 or len(words) <= limit:
        return text

    head = words[:limit]
    stripped = "".join(CLAUSE_ENDINGS)
    min_keep = max(1, limit // 2)
    for i in range(len(head) - 1, -1, -1):
        if i + 1 < min_keep:
            break
        if head[i].endswith(CLAUSE_ENDINGS):
            return " ".join(head[: i + 1]).rstrip(stripped)
    return " ".join(head).rstrip(stripped + ".") + "…"


def most_distant(manifest: TemplateManifest, taken: set[ColorRef]) -> ColorRef | None:
    """Самый непохожий на уже занятые свободный акцент темы.

    Задача фикса — сделать серии различимыми, а не красивыми: ближайший по ΔE цвет дал бы
    две почти одинаковые серии вместо двух одинаковых. Поэтому берётся максимум
    минимального расстояния, а не минимум.
    """
    free = [ref for ref in SERIES_PALETTE if ref not in taken]
    if not free:
        return None
    if not taken:
        return free[0]
    colors = manifest.theme.colors
    return max(
        free,
        key=lambda ref: min(delta_e_rgb(colors.get(ref), colors.get(other)) for other in taken),
    )


def _order(finding: Finding) -> tuple[int, str, str, str]:
    """Блочные фиксы применяются до слайдовых.

    `split_slide` перекраивает состав блоков, и сокращённый пункт должен доехать до него
    уже сокращённым — иначе правка либо уедет на слайд-продолжение в исходном виде,
    либо потеряется вместе с прежним составом блоков.
    """
    return (
        1 if finding.auto_fix is AutoFix.SPLIT_SLIDE else 0,
        finding.slide_id or "",
        finding.check_id,
        finding.finding_id,
    )


def _record(finding: Finding, outcome: Outcome) -> Finding:
    key = "fix" if outcome.applied else "fix_skipped"
    return _replace(
        finding,
        auto_fix_applied=outcome.applied,
        evidence={**finding.evidence, key: outcome.note},
    )


def _climbed_onto(
    slide: SlideIR, block: Block, moved: BBox, manifest: TemplateManifest
) -> str | None:
    """Сосед, на которого блок наехал бы после подтяжки, — или `None`, если таких нет.

    Мерило — не «пересекается ли», а «стало ли хуже»: блок, уже лежащий на соседе,
    сдвинуть к направляющей можно, лишь бы не глубже. Иначе починка отказывалась бы
    там, где сама же и исправляет положение.

    Подложка во весь слайд соседом не считается: она лежит под контентом по замыслу —
    то же правило `FULL_BLEED_SHARE`, по которому её пропускает `layout.overlap`.
    """
    before = block.bbox
    slide_box = manifest.slide_size.bbox
    if covers(moved, slide_box, FULL_BLEED_SHARE):
        return None
    for other, other_box in positioned_blocks(slide, manifest):
        if other.block_id == block.block_id or covers(other_box, slide_box, FULL_BLEED_SHARE):
            continue
        was = before.intersection_area(other_box) if before is not None else 0
        if moved.intersection_area(other_box) > was:
            return other.block_id
    return None


def _with_block(slide: SlideIR, block: Block) -> list[Block]:
    return [block if b.block_id == block.block_id else b for b in slide.blocks]


def _without(fit_report: dict[str, Any], block_id: str) -> dict[str, Any]:
    return {k: v for k, v in fit_report.items() if k != block_id}


def _free_slide_id(slides: list[SlideIR], base: str) -> str:
    taken = {s.slide_id for s in slides}
    for suffix in range(2, len(slides) + 3):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    raise AssertionError("свободный slide_id не найден")  # pragma: no cover


def _continuation_mark(language: str) -> str:
    return _CONTINUATION.get(language, _CONTINUATION["en"])


def _int_or_none(raw: str | None) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _replace[M: DomainModel](model: M, **changes: Any) -> M:
    """Копия модели с изменёнными полями — **через валидацию**.

    `model_copy(update=...)` в pydantic v2 валидацию не запускает: отрицательный кегль
    или координата мимо ограничения дожили бы до рендерера. Фикс обязан отдавать модель,
    прошедшую те же проверки, что и композиция (ADR-001).

    Поля берутся по `model_fields`, а не через `model_dump()`: дамп добавляет вычисляемые
    свойства (`BBox.right`, `BBox.bottom`), а модели домена запрещают лишние ключи —
    обратная валидация падала бы на любой находке с рамкой.
    """
    data: dict[str, Any] = {name: getattr(model, name) for name in type(model).model_fields}
    return type(model).model_validate({**data, **changes})
