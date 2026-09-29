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

from deckforge.composition.assign import RecipeAssignment
from deckforge.composition.free_space import (
    clip,
    effective_capacity,
    has_body_slot,
    spare_zone,
)
from deckforge.composition.layout_picker import pick_layout
from deckforge.composition.passport import fit_measure
from deckforge.composition.places import (
    at_the_ceiling,
    blocks_for_places,
    by_place,
    longest_word,
    merged,
    overflowing_places,
    places_brief,
    response_schema,
    shorten_request,
    trimmed_to_fit,
)
from deckforge.composition.recipe_binding import bind_to_recipe
from deckforge.composition.recipe_picker import pick_recipe, why_recipe
from deckforge.composition.visual_selector import select_chart
from deckforge.designsystem import DesignSystem
from deckforge.designsystem.models import Recipe
from deckforge.domain.base import BBox
from deckforge.domain.content import ContentPackage, Fact
from deckforge.domain.enums import ListStyle, TextRole
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
from deckforge.domain.template import LayoutCapacity, LayoutSpec, TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import InferenceClient, InferenceError
from deckforge.inference.structured import generate_json, generate_model
from deckforge.layout.by_design import DesignRules
from deckforge.layout.constraints import solve_positions
from deckforge.layout.diagram import SUPPORTED_PATTERNS
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fitting import fit_block
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing.capacity import lines_that_fit
from deckforge.registry import get_prompt_registry

#: Версия промпта, которая пишет текст **под места примера** (план Б, шаг 3). Названа
#: путём сборки, а не реестром: пути `legacy` и `by_example` живут рядом до приёмки,
#: и схемы ответа у них разные — активная версия принадлежит прежнему пути, пока он
#: не снят. Когда приёмка пройдена, `active` в `prompts/registry.yaml` становится этой
#: версией (файл тимлида), и константа уходит.
PLACES_PROMPT_VERSION = "2.1.0"

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
#: Цитата, callout и список — заказы элементов дизайн-системы (`plan-by-the-design-system`):
#: вид после двоеточия — `tone` у callout и `style` у списка (`_fulfils`).
_ORDERED_BLOCK: dict[str, type[Block]] = {
    "kpi": KpiBlock,
    "table": TableBlockIR,
    "image": ImageBlock,
    "chart": ChartBlock,
    "smartart": SmartArtBlock,
    "quote": QuoteBlock,
    "callout": CalloutBlock,
    "bullets": BulletsBlock,
}


def _fulfils(order: str, block: Block) -> bool:
    """Выполняет ли блок заказ плана.

    У схемы и диаграммы вид после двоеточия — подсказка композитору, а не условие:
    вид схемы выбирает он сам, тип диаграммы — правило по данным. У элементов
    дизайн-системы вид и есть заказ: callout «риск» вместо заказанного «инсайта» —
    другой элемент ДС, а маркированный список вместо иконочного — не тот список.
    """
    kind, _, detail = order.partition(":")
    wanted = _ORDERED_BLOCK.get(kind)
    if wanted is None or not isinstance(block, wanted):
        return False
    if isinstance(block, CalloutBlock) and detail:
        return block.tone.value == detail
    if isinstance(block, BulletsBlock) and detail:
        return (block.style or ListStyle.BULLETED).value == detail
    return True


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


def _target_chars(
    capacity: LayoutCapacity, variant: VariantProfile, recipe: Recipe | None
) -> int:
    """Сколько знаков просить у модели. У слайда по рецепту рамка чужая: просим ровно
    столько, сколько держит самая тесная зона, а не сколько поместилось бы в плейсхолдер."""
    if recipe is not None:
        zones = [zone.capacity_chars for zone in recipe.zones if zone.capacity_chars > 0]
        if zones:
            return min(zones)
    return round(capacity.max_chars_body * variant.capacity_ratio())


def _target_bullets(
    capacity: LayoutCapacity, facts: list[Fact], recipe: Recipe | None
) -> int:
    """Сколько пунктов просить. Ряд шаблона на три карточки — значит три пункта,
    иначе четвёртый окажется за краем композиции."""
    if recipe is not None and recipe.repeats:
        return max(1, min(recipe.repeats, len(facts) or recipe.repeats))
    return max(2, min(capacity.max_bullets, len(facts) or 3))


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
        "list_styles": list_styles,
        "callouts": callouts,
        "icon_examples": icon_examples,
    }


class SlideComposer:
    def __init__(
        self,
        llm_client: InferenceClient,
        profile: str | None = None,
        fonts: FontLibrary | None = None,
    ) -> None:
        self.llm = llm_client
        self.profile = profile
        #: Библиотека шрифтов шаблона. Нужна пути `by_example`: текст, написанный под места,
        #: проверяется тем же вписыванием, которым мерился паспорт (`passport.fit_measure`),
        #: и мерить его другими метриками — значит обещать одно, а верстать другое.
        self.fonts = fonts
        #: Что композиция изменила или выбросила. Забирает узел графа в отчёт прогона.
        self.notes: list[str] = []
        #: Почему слайд собран так (Т7): рецепт или макет, путь выбора, фраза для человека.
        #: По `slide_id`: слайды компонуются параллельно, порядок наводит узел графа.
        self.choices: dict[str, dict[str, object]] = {}

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
        previous_recipe: str | None = None,
        assignment: RecipeAssignment | None = None,
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

        `assignment` — назначенный до текста пример (ADR-009, узел `assign`). Есть
        назначение с примером и паспортом — слайд идёт путём `by_example`: модель пишет
        текст **под места этого примера**, а не под макет. Нет назначения — путь прежний,
        байт в байт. В назначении примера нет (`recipe_id is None`) — слайд собирается по
        макету и дизайн-системе, **без** подбора примера: «нет» — это решение, не пропуск.
        """
        layout = pick_layout(slide, manifest, variant)
        if assignment is not None and design_system is not None:
            recipe = next(
                (
                    item
                    for item in design_system.recipes
                    if item.recipe_id == assignment.recipe_id and item.passport is not None
                ),
                None,
            )
            if recipe is not None:
                return await self._for_places(
                    slide,
                    content,
                    manifest,
                    variant,
                    seed,
                    layout=layout,
                    design_system=design_system,
                    recipe=recipe,
                    assignment=assignment,
                    no_think=no_think,
                )
        rules = DesignRules(manifest, design_system)
        # Композиция шаблона под этот слайд (таск 05b). Вид назвал план, пример выбрал
        # счёт; модель о рецепте не знает — ей уходят только лимиты его зон, теми же
        # словами «вместимость», что и у плейсхолдеров.
        facts = [fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None]
        #: Сколько знаков слайду есть сказать: заголовок и факты, которые он показывает.
        #: Оценка сверху — модель перепишет факты короче, — но единственная, какая есть
        #: до ответа модели (RG23).
        needs_chars = len(slide.headline) + sum(len(fact.text) for fact in facts)
        explain: dict[str, object] = {}
        # Назначение «примера нет» (`recipe_id is None`: схема, callout, KPI без примера) —
        # решение узла `assign`, а не пропуск: ближайший пример здесь не подбирается.
        # Иначе слайд, который назначение отправило путём дизайн-системы, получал бы старым
        # счётом «самый вместительный» пример — на VK Tech 29.09 `ex018` четыре раза подряд,
        # а выноски и схемы ложились в его карточки (change `no-example-means-no-example`).
        unassigned = assignment is not None and assignment.recipe_id is None
        recipe = (
            pick_recipe(
                slide,
                design_system.recipes,
                previous_recipe,
                has_asset=bool(slide.asset_refs),
                needs_chars=needs_chars,
                # Откат структурного слайда на родственный вид называется в отчёте
                # прогона (RG8, `closing-slide-has-a-recipe`).
                notes=self.notes,
                explain=explain,
            )
            if design_system is not None and not unassigned
            else None
        )
        self.choices[slide.slide_id] = {
            "slide_id": slide.slide_id,
            "intent": slide.intent.value,
            "visual": slide.suggested_visual,
            "recipe_id": recipe.recipe_id if recipe is not None else None,
            "recipe_kind": recipe.kind.value if recipe is not None else None,
            "layout_id": layout.layout_id,
            "layout_kind": layout.kind.value,
            # Причина — из назначения: выбор «без примера» сделан до текста (ADR-009).
            "why": assignment.reason
            if unassigned and assignment is not None
            else why_recipe(explain, recipe)
            if design_system is not None
            else "дизайн-системы нет — слайд собран по макету",
        }
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
            target_chars=_target_chars(capacity, variant, recipe),
            target_bullets=_target_bullets(capacity, facts, recipe),
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
        composed = self._bind(
            raw, slide, layout, manifest, variant, seed, content, chart_type, bundle.ref, rules
        )
        # Рецепт применяется последним: сначала слайд собирается как обычно, потом его
        # текст раскладывается по зонам шаблона. Так слайд без рецепта не меняется
        # ни на строку, а слайд с рецептом теряет координаты — рамку ему даёт автор.
        return (
            bind_to_recipe(composed, recipe, self.notes) if recipe is not None else composed
        )

    async def _for_places(
        self,
        slide: SlidePlan,
        content: ContentPackage,
        manifest: TemplateManifest,
        variant: VariantProfile,
        seed: int,
        *,
        layout: LayoutSpec,
        design_system: DesignSystem,
        recipe: Recipe,
        assignment: RecipeAssignment,
        no_think: bool,
    ) -> SlideIR:
        """Текст под места назначенного примера (план Б, шаг 3, ADR-009).

        Порядок обратный прежнему: сначала известны места, потом пишется текст. Схема
        ответа собирается из паспорта (`places.response_schema`) — предел знаков каждого
        места держит грамматика, а не просьба в промпте; ответ ложится в места один
        к одному, и снимать при раскладке нечего.

        За схемой остаётся ширина букв: предел считает знаки, а место меряется шрифтом.
        Не вставшее место получает один повторный запрос с **замеренным** пределом этого
        текста и, если не помогло, обрезку по словам — названную в отчёте.

        Сам предел схемы стоит **выше** ёмкости места (К1, круг 2): грамматика держит его
        знаками и обрывает слово ровно на нём. Настоящий предел модель узнаёт из промпта,
        а текст, упёршийся в потолок схемы, считается оборванным и зовёт повтор.
        """
        passport = recipe.passport
        if passport is None:  # pragma: no cover — вызывающий проверяет паспорт
            raise CompositionError(
                f"слайд {slide.slide_id}: у примера {recipe.recipe_id} нет паспорта"
            )
        facts = [fact for ref in slide.fact_refs if (fact := content.fact(ref)) is not None]
        row_fill = assignment.row_fill
        brief = places_brief(passport, row_fill)
        asked = len(brief["single_places"]) + sum(
            row["count"] * len(row["cells"]) for row in brief["place_rows"]
        )

        bundle = get_prompt_registry().load(
            "slide_composer", profile=self.profile, version=PLACES_PROMPT_VERSION
        )
        system, user = bundle.render(
            slide=slide,
            facts=facts,
            recipe_kind=recipe.kind.value,
            variant=variant.variant_id,
            seed=seed,
            language=content.brief.language,
            brief=content.brief,
            no_think=no_think,
            **brief,
        )

        def ask(text: str, schema: dict[str, Any], attempt: int) -> dict[str, Any]:
            answer, _completion = generate_json(
                self.llm,
                system=system,
                user=text,
                response_schema=schema,
                # Тот же seed повторил бы тот же текст, а его уже отвергло место.
                seed=seed + attempt,
                temperature=bundle.meta.temperature,
                top_p=bundle.meta.top_p,
                max_tokens=bundle.meta.max_tokens,
                schema_name="SlidePlaces",
                skill_ref=bundle.ref,
            )
            return answer

        # Запас предела схемы меряется словами материала слайда (К1): у тесного места
        # полторы ёмкости не дают и одного слова, и оно оборвалось бы снова.
        longest = longest_word([slide.headline, *(fact.text for fact in facts)])
        schema = response_schema(passport, row_fill, longest=longest)
        answer = await asyncio.to_thread(ask, user, schema, 0)
        blocks = blocks_for_places(passport, row_fill, answer)
        if not blocks:
            raise CompositionError(
                f"слайд {slide.slide_id}: модель не написала ни одного из {asked} мест "
                f"примера {recipe.recipe_id}"
            )
        if len(blocks) < asked:
            self._note(
                slide.slide_id,
                f"мест примера {recipe.recipe_id} заказано {asked}, написано {len(blocks)}: "
                "пустые места вёрстка удалит вместе с их группой",
            )

        fits = fit_measure(manifest, design_system, self.fonts)

        def to_shorten(
            written: list[TextBlock], asked: dict[str, Any]
        ) -> tuple[dict[str, int], list[str]]:
            """Места, которые надо сократить: не встало по ширине или оборвано грамматикой.

            Замер вписывания обрубок не видит — он короче места и честно «встаёт»
            (К1, круг 2). Поэтому рядом с замером стоит признак «упёрся в потолок схемы»,
            и предел такому месту — его настоящая ёмкость, названная промптом.
            """
            out = overflowing_places(recipe, fits, written)
            broken = at_the_ceiling(passport, row_fill, written, asked)
            for zone, hard in broken.items():
                out.setdefault(zone, hard)
            return out, sorted(broken)

        limits, broken = to_shorten(blocks, schema)
        if broken:
            self._note(
                slide.slide_id,
                f"текст {len(broken)} мест упёрся в предел схемы — считаю оборванным "
                "грамматикой и прошу короче",
            )
        wanted: dict[str, int] = {}
        if limits:
            by_id = by_place(passport, limits)
            # Место, которое не держит и одного слова, сокращать бессмысленно: короче
            # слова текста не бывает. Такому месту кегль спустит вёрстка, а просить
            # у модели «до нуля знаков» значило бы потерять место (WorkSpace `ex024`,
            # место заголовка в девять знаков: повтор вернул пустую строку).
            wanted.update({pid: chars for pid, chars in by_id.items() if chars > 0})
            wordless = sorted(pid for pid, chars in by_id.items() if chars <= 0)
            if wordless:
                self._note(
                    slide.slide_id,
                    f"места {', '.join(wordless)} не держат и одного слова этого текста: "
                    "он остаётся, кегль ему спустит вёрстка",
                )
        if limits and wanted:
            self._note(
                slide.slide_id,
                f"по ширине букв не встали места {', '.join(sorted(wanted))} — "
                "один повторный запрос с замеренным пределом",
            )
            try:
                retry_schema = response_schema(passport, row_fill, wanted, longest)
                retried = await asyncio.to_thread(
                    ask,
                    f"{user}\n\n{shorten_request(wanted)}",
                    retry_schema,
                    1,
                )
            except InferenceError as error:
                self._note(slide.slide_id, f"повторный запрос не удался ({error})")
            else:
                # Ответ повтора ложится поверх первого: место, которое он вернул пустым,
                # остаётся с прежним текстом, а не теряется.
                if again := blocks_for_places(passport, row_fill, merged(answer, retried)):
                    blocks = again
                    limits, _ = to_shorten(blocks, retry_schema)
        if limits:
            by_block = {block.block_id: block.zone_id for block in blocks}
            blocks, cut = trimmed_to_fit(blocks, limits)
            for block_id, (before, after) in sorted(cut.items()):
                held = limits.get(by_block.get(block_id) or "", 0)
                self._note(
                    slide.slide_id,
                    f"блок {block_id} обрезан по словам под место: {before} → {after} знаков"
                    + (
                        ""
                        if after <= held
                        else f" — место держит {held}, а первое слово длиннее: "
                        "кегль ему спустит вёрстка"
                    ),
                )

        self.choices[slide.slide_id] = {
            "slide_id": slide.slide_id,
            "intent": slide.intent.value,
            "visual": slide.suggested_visual,
            "recipe_id": recipe.recipe_id,
            "recipe_kind": recipe.kind.value,
            "layout_id": layout.layout_id,
            "layout_kind": layout.kind.value,
            # Причина — из назначения: выбор сделан до текста, и повторять его здесь
            # значило бы объяснять слайд вторым, уже неверным способом.
            "why": assignment.reason,
        }
        return SlideIR(
            slide_id=slide.slide_id,
            layout_id=layout.layout_id,
            variant=variant.variant_id,
            blocks=list(blocks),
            recipe_id=recipe.recipe_id,
            speaker_note=slide.speaker_note,
            provenance=Provenance(
                fact_refs=slide.fact_refs,
                prompt_version=bundle.ref,
                model=getattr(self.llm, "model", None),
                seed=seed,
            ),
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
        if not ordered or ordered.split(":")[0] not in _ORDERED_BLOCK:
            return
        if any(_fulfils(ordered, block) for block in blocks):
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

    def _drop_catalogue_fields(self, ir: SlideIR, slide_id: str) -> SlideIR:
        """Снять с ответа модели поля, которыми владеет каталог композиций шаблона.

        `recipe_id` слайда, `zone_id` блока и `fit_report` заполняет код: рецепт выбирает
        счёт (`pick_recipe`), зоны раскладывает `bind_to_recipe`, отчёт считает вписывание.
        Модель файла не видит вовсе (ADR-003) и назвать ни рецепт, ни зону не может.

        Спрашивать их у неё и не собирались, но `slide-recipes` добавил их в `SlideIR`,
        а `SlideIR` — это ещё и схема ответа промпта, и в `response_omit` они не попали.
        С версии промпта `1.4.0` схема их больше не просит (change
        `composer-response-schema-without-recipe`), и это первый барьер; здесь — второй.
        Пять прогонов 24.09 (`b5babbdac83f`, `98a2c58353f3`, `dc59f95047c0`, `edf7b44ebbb8`,
        `8242966c5847`) упали на записи: закрывающему слайду рецепт не достался
        (у шаблона нет вида `final`), `bind_to_recipe` его выдумку не перезаписал, и
        `recipe_id` вида `L12_15_title_slide_closing_step_a` с зонами `title`/`body`
        уехал в колоду как факт.

        Снимается здесь, до размещения свободных блоков: блок без плейсхолдера и без
        координат уходит в `freed` и получает рамку от решателя. Тем же ответом чинится
        и вписывание, и запись — дальше по конвейеру цепочка уже не собирается, потому
        что у блока с `zone_id` нет рамки, а писатель без рамки рисовать не умеет.

        Второй барьер не лишний: грамматика llama.cpp не обещает, что лишнего ключа
        в ответе не будет, `pattern` из схемы и вовсе вырезается (#50), а профиль `dev`
        закреплён на `1.0.0` — там схема прежняя.
        """
        named: list[str] = []
        if ir.recipe_id:
            named.append(f"рецепт {ir.recipe_id}")
        zones = sorted({zone for block in ir.blocks if (zone := block.zone_id)})
        if zones:
            named.append("зоны " + ", ".join(zones))
        if ir.fit_report:
            named.append("отчёт о вписывании")
        if not named:
            return ir

        self._note(
            slide_id,
            "модель назвала " + "; ".join(named) + " — снято: эти поля заполняет "
            "каталог композиций шаблона, а не модель",
        )
        blocks: list[Block] = [
            block.model_copy(update={"zone_id": None}) if block.zone_id else block
            for block in ir.blocks
        ]
        return ir.model_copy(update={"blocks": blocks, "recipe_id": None, "fit_report": {}})

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
        ir = self._drop_catalogue_fields(ir, slide.slide_id)
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
