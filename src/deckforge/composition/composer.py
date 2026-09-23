"""Композиция слайда: подбор макета из манифеста и распределение контента.

Change (11) `slide-composition`. Модель возвращает только валидный `SlideIR` (ADR-001).

Схема гарантирует форму, но не осмысленность: `layout_id`, которого нет в манифесте,
и `placeholder_idx`, которого нет в макете, формально валидны. Поэтому после валидации
слайд **привязывается к реальности**: макет ставится тот, что выбрало правило, чужие
плейсхолдеры и висячие ссылки выбрасываются.
"""

from __future__ import annotations

import asyncio
import re
from functools import partial
from typing import Any

from deckforge.composition.free_space import (
    clip,
    effective_capacity,
    has_body_slot,
    spare_zone,
)
from deckforge.composition.layout_picker import pick_layout
from deckforge.composition.visual_selector import select_chart
from deckforge.designsystem import DesignSystem
from deckforge.domain.base import BBox
from deckforge.domain.content import ContentPackage
from deckforge.domain.enums import ColorRef, ListStyle, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import (
    Block,
    BulletsBlock,
    CalloutBlock,
    ChartBlock,
    IconBlock,
    ImageBlock,
    KpiBlock,
    Provenance,
    QuoteBlock,
    SlideIR,
    SmartArtBlock,
    TextBlock,
)
from deckforge.domain.slide import TableBlock as TableBlockIR
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import InferenceClient
from deckforge.inference.structured import generate_model
from deckforge.layout.by_design import ACCENT_SLOTS, DesignRules
from deckforge.layout.constraints import solve_positions
from deckforge.layout.diagram import SUPPORTED_PATTERNS
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fitting import fit_block
from deckforge.parsing.capacity import lines_that_fit
from deckforge.registry import get_prompt_registry

#: Короче этого заголовок не режется: два слова — уже не вывод, а обрубок. Такой случай
#: означает, что рамка мала для любого текста, и дальше это забота вёрстки (кегль вниз).
_MIN_HEADLINE_WORDS = 2

#: Многоточие, которым кончается подрезанный заголовок. Знак того, что мысль
#: не уместилась, а не того, что автор так задумал.
_ELLIPSIS = "…"

#: Предел Приложения 1 ТЗ. Вместимость макета может быть мягче — берётся строгий.
MAX_BULLETS_BY_SPEC = 6

#: Короче этого слово ничего не различает: «этот», «есть», «для» стоят в любом тексте.
_SIGNIFICANT_WORD = 5

#: Сколько первых букв берётся от слова при сверке. Русский текст склоняется,
#: и «дизайн-систему» с «дизайн-система» — одно слово, а не два разных.
_STEM = 6

#: Какая доля подписей схемы, найденная в одном текстовом блоке, делает его повтором.
#: Больше половины: одно-два общих слова — это общая тема, а не тот же список.
_DUPLICATE_SHARE = 0.6

#: Стрелка между шагами, как её пишут руками и как её оставляет markitdown: знак «→»
#: и его родня, «->», «=>», «—>». Пробелы вокруг — часть разделителя.
_ARROW = re.compile(r"\s*(?:[→⟶➔➜➝⇒]|[-–—=]{1,2}>)\s*")

#: Сколько стрелок делает строку процессом. Две, то есть три шага: одна стрелка между
#: двумя значениями («10 → 20 %») — это изменение показателя, а не порядок работ.
_PROCESS_ARROWS = 2

#: Номер пункта, который модель вписала в текст: «1. », «2) ». Нумерует список сам (DG3),
#: и номер в тексте рядом с автонумерацией вышел бы дважды — а аудит чисел звал бы его
#: выдуманным («Числа «2» нет в исходных материалах»).
_ORDINAL = re.compile(r"^\s*(\d{1,2})[.)]\s+")

#: Какой блок IR отвечает заказу плана (`SlidePlan.suggested_visual`). Словарь заказов
#: собирает слой планирования; здесь — только соответствие заказа типу блока.
_ORDERED_BLOCK: dict[str, type[Block]] = {
    "kpi": KpiBlock,
    "table": TableBlockIR,
    "image": ImageBlock,
    "chart": ChartBlock,
    "smartart": SmartArtBlock,
}


class CompositionError(RuntimeError):
    """Слайд собрать не удалось: от модели не осталось ни одного пригодного блока."""


#: Блоки, которые можно поставить свободно, если в макете нет подходящего плейсхолдера.
#: Текст теряться не должен: у VK WorkSpace макетов под текст нет вовсе, и раньше
#: основное содержание слайда молча исчезало.
#:
#: Схема и показатели здесь по той же причине, что и текст: это содержание слайда,
#: а не оформление. Диаграммы и таблицы в набор не входят — им нужен не просто
#: прямоугольник, а макет, который их допускает (`capacity.supports_*`).
#:
#: Цитата и callout (DG3) — тоже содержание, и плейсхолдера под них в шаблонах нет:
#: полосу и отбивку им рисует вёрстка по дизайн-системе в рамке от решателя.
_PLACEABLE_FREELY = (TextBlock, BulletsBlock, SmartArtBlock, KpiBlock, QuoteBlock, CalloutBlock)


def _why_not_free(block: Block, layout: LayoutSpec) -> str:
    """Почему блок этого вида нельзя поставить свободным — своими словами для каждого.

    Прежде заметка была одна на всех («ставить его свободно нельзя»), и по ней нельзя
    было понять, чего не хватило: макета, плейсхолдера или смысла."""
    capacity = layout.capacity
    if isinstance(block, IconBlock):
        return (
            "одиночная иконка свободным блоком заняла бы всю свободную часть слайда; "
            "знак у пунктов — иконочный список (bullets, style=icon)"
        )
    wants = {
        ChartBlock: ("диаграмме", capacity.supports_chart, "supports_chart"),
        TableBlockIR: ("таблице", capacity.supports_table, "supports_table"),
        ImageBlock: ("картинке", capacity.supports_image, "supports_image"),
    }.get(type(block))
    if wants is None:
        return "свободно этот вид не ставится"
    whom, supported, flag = wants
    return (
        f"{whom} нужен плейсхолдер макета, а модель его не назвала"
        if supported
        else f"{whom} нужен макет, который её допускает, а макет {layout.layout_id} — нет "
        f"(capacity.{flag})"
    )


def _slot_lines(layout: LayoutSpec, manifest: TemplateManifest) -> dict[int, int]:
    """Сколько строк вмещает каждое место под текст — в самом мелком кегле шкалы.

    Модель видела у плейсхолдера только номер и роль, и полоса высотой в одну строку
    для неё ничем не отличалась от тела: список из четырёх пунктов уезжал в строку
    0,8 см под заголовком VK Tech (прогон 3c492f118781) и ронял запись колоды.
    Мелкий кегль — потому что вписывание дойдёт до него, прежде чем сдаться:
    если и в нём строка одна, списку тут не место.
    """
    ladder = manifest.size_ladder_pt
    smallest = min(ladder) if ladder else None
    out: dict[int, int] = {}
    for ph in layout.placeholders:
        if ph.role is not TextRole.BODY:
            continue
        size = smallest or ph.size_pt
        if size:
            out[ph.idx] = lines_that_fit(ph, size)
    return out


def _stems(text: str) -> set[str]:
    """Начала значащих слов текста — тем и сверяются факт и слайд."""
    words = re.findall(r"[0-9a-zа-яё]+", text.lower())
    return {word[:_STEM] for word in words if len(word) >= _SIGNIFICANT_WORD}


def _is_lead_in(text: str) -> bool:
    """Зачин перечисления: «Для этого необходимо:». Своего содержания у него нет.

    Его смысл — в пунктах, которые идут следом, и на слайде он честно растворяется
    в них. Три прогона подряд (0c4470b85d0a, a8f47eaf4d3f, dfa40a2dc908) называли
    потерянным именно такой факт — находка, которая есть всегда и ничего не значит,
    учит не читать отчёт.
    """
    return text.rstrip().endswith(":")


def _text_of(block: Block) -> str:
    """Весь текст блока одной строкой. Картинка и диаграмма содержания в словах не несут."""
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, BulletsBlock):
        return " ".join(item.text for item in block.items)
    if isinstance(block, SmartArtBlock):
        # Элементы схемы — строки, а не объекты с текстом: у схемы подпись и есть элемент.
        return " ".join(block.items)
    if isinstance(block, KpiBlock):
        return " ".join(f"{item.value} {item.label}" for item in block.items)
    if isinstance(block, TableBlockIR):
        return " ".join([*block.header, *(cell for row in block.rows for cell in row)])
    if isinstance(block, QuoteBlock):
        return " ".join(part for part in (block.text, block.author) if part)
    if isinstance(block, CalloutBlock):
        return block.text
    return ""


def _arrow_steps(text: str) -> list[str]:
    """Шаги процесса, записанного строкой через стрелки. Пусто — это не процесс.

    Процесс — это не меньше `_PROCESS_ARROWS` стрелок и слова по обе стороны каждой:
    «А → Б → В». Висячая стрелка в конце строки шага не даёт, цепочка одних чисел
    («10 → 20 → 30 %») — тоже: это ход показателя, а не шаги работы.
    """
    parts = [part.strip(" .,;:") for part in _ARROW.split(text)]
    if len(parts) <= _PROCESS_ARROWS:
        return []
    if not all(re.search(r"[^\W\d_]", part) for part in parts):
        return []
    return parts


def _headline_text(words: list[str], whole: int) -> str:
    """Заголовок из оставшихся слов: с многоточием, если слова выброшены."""
    text = " ".join(words)
    return text if len(words) == whole else text.rstrip(" ,;:—-") + _ELLIPSIS


def _design_context(rules: DesignRules) -> dict[str, Any]:
    """Что промпт композитора знает о дизайн-системе: роли и виды, без координат и кеглей.

    Назначения стилей списка и видов callout берутся у дизайн-системы (`synthesized`) —
    тем же текстом, что на её странице: один ответ на вопрос «когда какой».
    """
    elements = {item.kind: item for item in rules.ds.synthesized}
    list_styles = [
        {"style": style.value, "purpose": elements[style.value].purpose}
        for style in ListStyle
        if style.value in elements
    ]
    callouts = [
        {"tone": kind.removeprefix("callout_"), "label": elements[kind].text,
         "purpose": elements[kind].purpose}
        for kind in ("callout_insight", "callout_risk")
        if kind in elements
    ]
    icon_examples = [item.text for item in rules.ds.synthesized if item.kind == "icon"]
    return {
        "accent_roles": [ref.value for ref in rules.role_accents()],
        "list_styles": list_styles,
        "callouts": callouts,
        "icon_examples": icon_examples,
    }


class SlideComposer:
    def __init__(self, llm_client: InferenceClient, profile: str | None = None) -> None:
        self.llm = llm_client
        self.profile = profile
        #: Что композиция изменила или выбросила. Забирает узел графа в отчёт прогона.
        self.notes: list[str] = []
        #: Заметка «роли цветов не измерены» — одна на прогон, а не на слайд (правило 10).
        self._cold_noted = False

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
        design_system: DesignSystem | None = None,
    ) -> SlideIR:
        """Наполняет макет содержимым слайда.

        `preserve_wording` — рычаг деградации. По умолчанию при нехватке места
        сокращается текст, а визуализация сохраняется: тип визуализации выбран под
        данные, а формулировку можно ужать без потери смысла. Если автор просил
        сохранить формулировки, жертвуется визуализация. Поля в брифе под это пока
        нет — запрос тимлиду в proposal.md.

        `no_think` добавляет в запрос «/no_think» — команду семейства Qwen3 не размышлять.
        Нужна для замера, сколько из 389 с композиции приходится на размышление.

        `design_system` — дизайн-система шаблона из состояния графа (DG2). По ней
        композиция называет модели роли цветов и виды списков и callout (не координаты),
        проверяет названный моделью цвет и разводит свободные блоки шагом `grid.spacing`.
        Нет — считается из манифеста (`DesignRules`).
        """
        layout = pick_layout(slide, manifest, variant)
        rules = DesignRules(manifest, design_system)
        facts = [fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None]
        dataset = content.dataset(slide.dataset_ref) if slide.dataset_ref else None
        chart_type = select_chart(dataset) if dataset is not None else None

        # Вместимость показывается та, что слайду действительно достанется. У макета
        # без места под тело своя — ноль, и промпт просил «не более 0 знаков»: модель
        # честно отдавала один заголовок, а колода выходила без текста (#62).
        body_free = not has_body_slot(layout)
        capacity = effective_capacity(layout, manifest)
        # Мест под текст может быть несколько: у VK Tech список размечен шестью
        # плейсхолдерами по строке вместо одного блока на шесть строк. Модель об этом
        # обязана знать, иначе весь список уедет в первое место высотой 0,4 см.
        body_slots = sum(1 for ph in layout.placeholders if ph.role is TextRole.BODY)
        slot_lines = _slot_lines(layout, manifest)

        bundle = get_prompt_registry().load("slide_composer", profile=self.profile)
        system, user = bundle.render(
            layout=layout,
            slide=slide,
            facts=facts,
            dataset=dataset,
            variant=variant.variant_id,
            seed=seed,
            size_ladder=manifest.size_ladder_pt,
            capacity=capacity,
            target_chars=round(capacity.max_chars_body * variant.capacity_ratio()),
            target_bullets=max(2, min(capacity.max_bullets, len(facts) or 3)),
            body_free=body_free,
            # B10. Свободная зона рядом с местом под тело: до сих пор её не предлагали
            # никому, и на шаблонах кейса это половина слайда.
            spare_zone=spare_zone(layout, manifest),
            body_slots=body_slots,
            slot_lines=slot_lines,
            smartart_patterns=sorted(pattern.value for pattern in SUPPORTED_PATTERNS),
            capacity_ratio=variant.capacity_ratio(),
            language=content.brief.language,
            brief=content.brief,
            preserve_wording=preserve_wording,
            chart_type=chart_type.value if chart_type else None,
            no_think=no_think,
            # DG3. Модель не видит координат (PPTBench): ей уходят роли и виды из
            # дизайн-системы, а не EMU и не кегли.
            **_design_context(rules),
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
            raw, slide, layout, manifest, variant, seed, content, chart_type, bundle.ref, rules
        )

    def _trim_headline(
        self, block: TextBlock, layout: LayoutSpec, manifest: TemplateManifest, slide_id: str
    ) -> TextBlock:
        """Заголовок по границе слова — ровно до того, что помещается в его рамку.

        Предел модели названа (`headline_chars` планировщика, правило 4 композитора),
        но она его не держит: прогоны d573740bddd3, 05884387b999 и 4a196eb4f56b —
        10 заголовков из 10 длиннее места, и дальше их режет вёрстка, по буквам.

        Мерило — то же `fit_block`, которым потом меряет слой вёрстки: предел в знаках
        считается по средней ширине знака и врёт в обе стороны (на VK WorkSpace он давал
        46 знаков там, где помещается 30). Слово выбрасывается, пока текст не влезет.
        """
        if block.placeholder_idx is None or layout.placeholder(block.placeholder_idx) is None:
            return block  # свободному блоку рамку ещё не дали: мерить нечего

        words = block.text.split()
        whole = len(words)
        while True:
            # Меряется ровно то, что будет записано: многоточие занимает место, и без него
            # подрезка останавливалась на строку раньше, чем нужно (CI #73 — 46 знаков
            # вместо 45, и заголовок снова переполнял рамку).
            candidate = block.model_copy(update={"text": _headline_text(words, whole)})
            if not fit_block(candidate, layout, manifest).overflow:
                break
            if len(words) <= _MIN_HEADLINE_WORDS:
                break
            words = words[:-1]

        if len(words) == whole:
            return block

        trimmed = _headline_text(words, whole)
        self._note(
            slide_id,
            f"заголовок подрезан под рамку макета: {len(block.text)} → {len(trimmed)} знаков",
        )
        return block.model_copy(update={"text": trimmed})

    def _note_facts_left_out(
        self, slide: SlidePlan, blocks: list[Block], content: ContentPackage
    ) -> None:
        """Факты плана, от которых на слайде не осталось ни одного слова.

        Промпт требует использовать все переданные факты, но требование без проверки
        остаётся пожеланием: прогон 2ac85990b2f2, слайд s04 — три факта по плану,
        два тезиса на слайде. Аудит такую потерю не видит: `integrity.content_lost`
        ловит только слайд, где содержания нет вовсе.

        Сверка грубая и намеренно снисходительная: одно общее слово снимает подозрение.
        Цель — поймать выброшенный факт, а не измерить полноту пересказа.
        """
        written = _stems(" ".join(_text_of(block) for block in blocks))
        left_out = [
            fact.fact_id
            for ref in slide.fact_refs
            if (fact := content.fact(ref)) is not None
            and not _is_lead_in(fact.text)
            and (words := _stems(fact.text))
            and not words & written
        ]
        if left_out:
            self._note(
                slide.slide_id,
                f"факты {', '.join(left_out)} на слайд не попали: "
                "ни одного их значащего слова в тексте",
            )

    def _note_duplicated_visual(self, slide: SlidePlan, blocks: list[Block]) -> None:
        """Текст, который повторяет подписи схемы на том же слайде.

        Прогон 8f420f2c6621: плитки «Парсинг документов, Извлечение структуры…»
        и рядом абзац «Пайплайн включает парсинг, извлечение структуры…». Схема должна
        заменять перечисление, а не дублировать его. Текст код не удаляет — в абзаце
        бывает и то, чего в схеме нет, — но повтор называет.
        """
        for visual in (block for block in blocks if isinstance(block, SmartArtBlock)):
            labels = [_stems(item) for item in visual.items]
            labels = [stems for stems in labels if stems]
            if not labels:
                continue
            for block in blocks:
                if not isinstance(block, TextBlock | BulletsBlock):
                    continue
                if isinstance(block, TextBlock) and block.role is TextRole.TITLE:
                    continue
                written = _stems(_text_of(block))
                repeated = sum(1 for stems in labels if stems & written) / len(labels)
                if repeated >= _DUPLICATE_SHARE:
                    self._note(
                        slide.slide_id,
                        f"текст {block.block_id} повторяет подписи схемы {visual.block_id} "
                        f"({repeated:.0%}): схема должна заменять список, а не дублировать",
                    )

    def _note_missing_visual(self, slide: SlidePlan, blocks: list[Block]) -> None:
        """Заказ плана на визуализацию, который модель не выполнила.

        Блок за модель код не выдумывает: показатели без чисел в материалах — это
        выдуманные числа, а схема из ничего — оформление ради оформления. Но молчать
        тоже нельзя: план просил показать мысль, а слайд её пересказал абзацем.
        """
        ordered = slide.suggested_visual
        if not ordered:
            return
        wanted = _ORDERED_BLOCK.get(ordered.split(":")[0])
        if wanted is None or any(isinstance(block, wanted) for block in blocks):
            return
        self._note(slide.slide_id, f"план заказал «{ordered}», модель такого блока не дала")

    def _note_process_as_text(self, slide: SlidePlan, blocks: list[Block]) -> None:
        """Процесс, записанный строкой через стрелки, который так и остался текстом (A12).

        VK Tech s04, прогон d0b37773345e: «Анализ шаблона → извлечение структуры →
        генерация…» легло строкой 12 pt в полосу под заголовком. Стрелки — это порядок
        шагов, и место ему в схеме `process`, а не в строке, которую не прочтут как порядок.

        Схему за модель код не собирает — по той же причине, что и в `_note_missing_visual`:
        подписи узлов — это формулировки, а формулировки пишет модель. Но строку со стрелками
        называет. Если схема на слайде уже есть, повтор её подписей текстом ловит
        `_note_duplicated_visual`, и вторая заметка о том же не нужна. Заголовок не
        проверяется: процесс в заголовке — это вывод о порядке, а не сам порядок.
        """
        if any(isinstance(block, SmartArtBlock) for block in blocks):
            return
        for block in blocks:
            if isinstance(block, TextBlock) and block.role is not TextRole.TITLE:
                lines = [block.text]
            elif isinstance(block, BulletsBlock):
                lines = [item.text for item in block.items]
            else:
                continue
            for line in lines:
                if steps := _arrow_steps(line):
                    shown = " → ".join(steps[:3]) + (" → …" if len(steps) > 3 else "")
                    self._note(
                        slide.slide_id,
                        f"текст {block.block_id} — процесс строкой («{shown}», шагов "
                        f"{len(steps)}): стрелки просят схему process, а не строку",
                    )
                    break

    def _accent_by_role(self, block: Block, rules: DesignRules, slide_id: str) -> Block:
        """Цвет, названный моделью, — только акцент шаблона по роли дизайн-системы (DG3).

        Модель пишет `accent1` по привычке, а шаблон ставит акцентом третий слот (VK Tech,
        VK WorkSpace — `accent3` по площади примеров). Акцентный слот, которого нет среди
        акцентов по роли, снимается: цвет возьмёт вёрстка — акцент по роли, видимый на фоне
        макета (`DesignRules.block_accent`, полоса цитаты — `callout_accent`). Не акцентные
        слоты (`dk*`, `lt*`) не трогаются: это решение о тексте, а не об акценте.

        Роли не измерены (холодный шаблон, правило 10) — цвет модели остаётся как есть,
        и это называет одна заметка на прогон.
        """
        allowed = rules.role_accents()

        def foreign(ref: ColorRef | None) -> bool:
            return ref is not None and ref in ACCENT_SLOTS and ref not in allowed

        named: list[ColorRef | None] = []
        if isinstance(block, KpiBlock):
            named = [item.color_ref for item in block.items]
        elif isinstance(block, SmartArtBlock):
            named = list(block.color_refs)
        elif isinstance(block, IconBlock):
            named = [block.color_ref]
        elif isinstance(block, QuoteBlock | CalloutBlock):
            named = [block.accent_ref]
        if not any(ref is not None for ref in named):
            return block
        if not allowed:
            if not self._cold_noted:
                self._cold_noted = True
                self.notes.append(
                    "дизайн-система: роли цветов не измерены — цвета блоков, названные "
                    "моделью, оставлены как есть"
                )
            return block
        dropped = sorted({ref.value for ref in named if ref is not None and foreign(ref)})
        if not dropped:
            return block

        if isinstance(block, KpiBlock):
            block = block.model_copy(update={"items": [
                item.model_copy(update={"color_ref": None}) if foreign(item.color_ref) else item
                for item in block.items
            ]})
        elif isinstance(block, SmartArtBlock):
            block = block.model_copy(
                update={"color_refs": [ref for ref in block.color_refs if not foreign(ref)]}
            )
        elif isinstance(block, IconBlock):
            block = block.model_copy(update={"color_ref": None})
        elif isinstance(block, QuoteBlock | CalloutBlock):
            block = block.model_copy(update={"accent_ref": None})
        self._note(
            slide_id,
            f"блок {block.block_id}: {', '.join(dropped)} шаблон акцентом не ставит — "
            f"цвет по роли дизайн-системы ({', '.join(ref.value for ref in allowed)})",
        )
        return block

    def _list_style(self, block: BulletsBlock, slide_id: str) -> BulletsBlock:
        """Стиль списка, который действительно выйдет на слайде (DG3).

        Модель выбирает стиль по смыслу пунктов, композиция сводит выбор с тем, что
        вёрстка может нарисовать, и называет каждое расхождение:

        * номера в тексте пунктов («1. », «2. » подряд) — это нумерованный список,
          записанный вручную: номера снимаются, стиль — `numbered`. У списка, который
          модель и так назвала нумерованным, номера снимаются всегда — иначе рядом
          с автонумерацией вышло бы «1. 1. »;
        * иконочный список в плейсхолдере или с пунктом без иконки — маркированный:
          иконку к строке плейсхолдера не привязать, а список с дырой выглядит сломанным;
        * у всех пунктов свободного списка без стиля есть иконки — это иконочный список;
        * иконки у списка другого стиля не рисуются — снимаются.
        """
        style = block.style
        items = block.items

        numbers = [_ORDINAL.match(item.text) for item in items]
        # Один пункт с «1. » — нумерация, только если модель сама назвала список
        # нумерованным (хвост мог срезать предел пунктов); иначе это просто число.
        counted = len(items) > 1 or style is ListStyle.NUMBERED
        if counted and all(numbers) and [
            int(match.group(1)) for match in numbers if match
        ] == list(range(1, len(items) + 1)):
            items = [
                item.model_copy(update={"text": item.text[match.end():]})
                for item, match in zip(items, numbers, strict=True)
                if match
            ]
            self._note(
                slide_id,
                f"буллеты {block.block_id}: номера пунктов в тексте сняты — "
                + ("нумерует список" if style is ListStyle.NUMBERED
                   else "список нумерованный"),
            )
            style = ListStyle.NUMBERED

        icons = [item.icon for item in items]
        if style is ListStyle.ICON:
            why = (
                f"в плейсхолдере {block.placeholder_idx} иконку к строке не привязать"
                if block.placeholder_idx is not None
                else f"иконки нет у {sum(1 for icon in icons if not icon)} пунктов "
                f"из {len(items)}"
                if not all(icons)
                else None
            )
            if why is not None:
                self._note(slide_id, f"иконочный список {block.block_id}: {why} — маркированный")
                style = ListStyle.BULLETED
        elif style is None and all(icons) and block.placeholder_idx is None:
            self._note(
                slide_id, f"буллеты {block.block_id}: иконки у всех пунктов — иконочный список"
            )
            style = ListStyle.ICON
        if style is not ListStyle.ICON and any(icons):
            items = [item.model_copy(update={"icon": None}) for item in items]
            self._note(
                slide_id,
                f"буллеты {block.block_id}: иконки пунктов сняты — стиль списка "
                f"{(style or ListStyle.BULLETED).value}",
            )

        if style is block.style and items == block.items:
            return block
        return block.model_copy(update={"style": style, "items": items})

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
        rules: DesignRules | None = None,
    ) -> list[Block]:
        """Даёт координаты блокам, оставшимся без плейсхолдера.

        Решатель из слоя `layout` делит свободную часть области контента между ними
        и не даёт залезть на занятые плейсхолдеры. Плейсхолдер, выходящий за поля шаблона,
        учитывается своей видимой частью: решателю нельзя отдать рамку шире области,
        но и забыть про неё нельзя — текст встанет поверх заголовка.

        Промежуток между свободными блоками — шаг шкалы отступов дизайн-системы (DG3):
        чему кратен отступ, решает она, а не решатель.
        """
        content = manifest.content_bbox
        rules = rules if rules is not None else DesignRules(manifest)
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
            boxes = solve_positions(
                [*fixed, *((block_id, None) for block_id in freed)],
                manifest,
                gap_emu=rules.block_gap_emu(),
            )
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
        rules: DesignRules | None = None,
    ) -> SlideIR:
        rules = rules if rules is not None else DesignRules(manifest)
        known_placeholders = {ph.idx for ph in layout.placeholders}
        known_datasets = {d.dataset_id for d in content.datasets}
        known_assets = {a.asset_id for a in content.assets}
        max_bullets = min(MAX_BULLETS_BY_SPEC, layout.capacity.max_bullets or MAX_BULLETS_BY_SPEC)

        blocks: list[Block] = []
        freed: list[str] = []
        #: Плейсхолдеры, которые уже заняты блоком. Один плейсхолдер — один блок: два
        #: блока в одном месте — это рамка поверх рамки, наложение в 100 % площади
        #: и находка `layout.overlap` (B9). Решатель такой пары не разводит и не обязан:
        #: место обоим дал не он, а модель, назвав один и тот же плейсхолдер дважды.
        taken: set[int] = set()
        for block in ir.blocks:
            if isinstance(block, TextBlock) and block.role is TextRole.TITLE:
                block = self._trim_headline(block, layout, manifest, slide.slide_id)
            idx = getattr(block, "placeholder_idx", None)

            if idx is not None and (idx not in known_placeholders or idx in taken):
                why = (
                    f"плейсхолдера {idx} нет в макете {layout.layout_id}"
                    if idx not in known_placeholders
                    else f"плейсхолдер {idx} макета {layout.layout_id} уже занят"
                )
                if isinstance(block, _PLACEABLE_FREELY):
                    # Текст не выбрасывается: в шаблоне может не быть ни одного макета
                    # под содержание, и тогда свободный блок в области контента —
                    # единственный способ ничего не потерять.
                    block = block.model_copy(update={"placeholder_idx": None})
                    idx = None
                    freed.append(block.block_id)
                    self._note(
                        slide.slide_id,
                        f"блок {block.block_id}: {why}, поставлен свободным блоком",
                    )
                else:
                    self._note(
                        slide.slide_id,
                        f"блок {block.block_id} ({block.type}) отброшен: {why}; "
                        + _why_not_free(block, layout),
                    )
                    continue
            elif idx is not None:
                taken.add(idx)
                if isinstance(block, TextBlock) and block.color_ref is not None:
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
                else:
                    # Диаграмме, таблице и картинке нужен не прямоугольник, а макет,
                    # который их допускает, — свободно их не поставить. Координаты
                    # от модели тут не спасение, а источник наложений: решатель их
                    # не видит, и рамка ложится поверх плейсхолдера (B9). Правило
                    # change `composer-no-model-coordinates` — «координатам модели
                    # не доверяем вовсе» — до этих трёх видов не дошло.
                    self._note(
                        slide.slide_id,
                        f"блок {block.block_id} ({block.type}) отброшен: "
                        + (
                            "координаты от модели не берём, а "
                            if block.bbox is not None
                            else "ни плейсхолдера, ни координат, а "
                        )
                        + _why_not_free(block, layout),
                    )
                    continue

            block = self._accent_by_role(block, rules, slide.slide_id)
            if isinstance(block, BulletsBlock):
                block = self._list_style(block, slide.slide_id)
            blocks.append(block)

        if freed:
            blocks = self._place_free(blocks, freed, layout, manifest, slide.slide_id, rules)

        if not blocks:
            raise CompositionError(
                f"слайд {slide.slide_id}: после отбраковки не осталось ни одного блока"
            )

        self._note_missing_visual(slide, blocks)
        self._note_facts_left_out(slide, blocks, content)
        self._note_duplicated_visual(slide, blocks)
        self._note_process_as_text(slide, blocks)

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
