"""Вёрстка по дизайн-системе шаблона. Change `draw-by-the-design-system` (DG3, сторона B).

Композиция и вёрстка перестают решать сами то, на что дизайн-система уже ответила
по слайдам-примерам шаблона (`designsystem`, #142):

* **акцент блока** — роль `accent` из `palette_roles`: цвет, который автор шаблона
  действительно ставил акцентом, а не `accent1` по порядку. В IR и в файле это
  по-прежнему имя слота темы (правило 5);
* **кегль числа** — `number_sizes`: крупный кегль, которым шаблон сам набрал показатель,
  приведённый к ступени шкалы шаблона (правило 6);
* **пропорции плитки** — `components` дизайн-системы;
* **полоса и отбивка цитаты и callout** — `synthesized`: шаг сетки дизайн-системы.

Холодный шаблон (правило 10): слайдов-примеров нет — ролей и кеглей дизайн-система
не измерила. Тогда поведение прежнее, а `cold_notes` называет это в заметках прогона:
«прежнее» без заметки неотличимо от «по дизайн-системе».

Слой `layout` стоит выше `designsystem` и LLM не вызывает. Здесь только чтение готовой
структуры и два порога алгоритма; ни одного числа шаблона.
"""

from __future__ import annotations

from dataclasses import dataclass

from deckforge.designsystem import DesignSystem, Origin, derive
from deckforge.designsystem.contrast import TextClass, readability, readable_ref, text_class
from deckforge.designsystem.models import ColorRoleKind, ComponentCard, SynthElement
from deckforge.domain.enums import CalloutTone, ColorRef, TextRole
from deckforge.domain.rules import delta_e_rgb, next_size_down
from deckforge.domain.template import ComponentKind, TemplateManifest

#: Акцентные слоты темы по порядку. Запасной ряд: роли не измерены или все измеренные
#: акценты на этом фоне не видны.
ACCENT_SLOTS: tuple[ColorRef, ...] = (
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
)

#: Наибольшая отбивка внутри блока — доля его ширины. Порог алгоритма, а не свойство
#: шаблона: шаг сетки бывает объявлен и шириной в шестую часть слайда (у одного шаблона
#: кейса «зазор» между направляющими — 5,7 см), и отбивка таким шагом съела бы цитату.
#: Шаг тогда делится пополам, пока не встанет в предел, — отношение полосы к отбивке,
#: заданное дизайн-системой, при этом сохраняется.
MAX_INSET_SHARE = 0.08

#: Как вид callout называется в `synthesized` — там его полоса, отбивка и подпись.
_CALLOUT_KIND: dict[CalloutTone, str] = {
    CalloutTone.INSIGHT: "callout_insight",
    CalloutTone.RISK: "callout_risk",
}

#: Какой по счёту акцент берёт callout этого вида: инсайт — главный акцент шаблона,
#: риск — следующий, чтобы два callout на слайде не выглядели одним.
_CALLOUT_ACCENT: dict[CalloutTone, int] = {CalloutTone.INSIGHT: 0, CalloutTone.RISK: 1}


@dataclass(frozen=True)
class KpiSizes:
    """Кегли показателя по дизайн-системе: значение и подпись — ступени шкалы шаблона."""

    #: Ступень шкалы, ближайшая к кеглю, которым шаблон набрал своё число.
    value_pt: float
    #: Мелкий кегль числа из дизайн-системы — подпись под значением.
    small_pt: float | None
    #: Что измерено в шаблоне, до приведения к шкале: для заметок и отчёта.
    measured_pt: float

    def label_for(self, value_pt: float, manifest: TemplateManifest) -> float:
        """Кегль подписи при этом кегле значения: мельче значения, со шкалы шаблона.

        Значение могло уступить кегль рамке — тогда подпись уходит на ступень под ним,
        а не остаётся вровень: иерархия «крупное число, мелкая подпись» важнее точного
        совпадения с мелким кеглем шаблона.
        """
        ladder = manifest.size_ladder_pt
        if self.small_pt is not None and self.small_pt < value_pt and self.small_pt in ladder:
            return self.small_pt
        return next_size_down(manifest, value_pt) or value_pt


@dataclass(frozen=True)
class Inset:
    """Полоса слева и отбивка текста от неё — в EMU."""

    bar_emu: int
    pad_emu: int


@dataclass(frozen=True)
class BoxedStyle:
    """Цитата или callout: кегль текста, кегль второй строки, подпись вида, шаг."""

    #: Роль, чья гарнитура и начертание у основного текста блока.
    role: TextRole
    text_pt: float
    #: Кегль строки автора у цитаты. У callout подпись вида идёт кеглем текста.
    minor_pt: float
    #: Подпись вида у callout («Ключевой инсайт», «Риск») — из дизайн-системы.
    label: str
    spacing_emu: int
    line_emu: int

    def inset(self, box_cx: int) -> Inset:
        """Отбивка шагом дизайн-системы, но не шире `MAX_INSET_SHARE` рамки.

        Отношение полосы к отбивке берётся у дизайн-системы (полоса — доля шага),
        поэтому при делении шага пополам полоса тоньшает вместе с ним.
        """
        limit = box_cx * MAX_INSET_SHARE
        pad = max(1, self.spacing_emu)
        while pad > limit and pad > 1:
            pad //= 2
        bar = max(1, round(pad * self.line_emu / self.spacing_emu)) if self.spacing_emu else 1
        return Inset(bar_emu=bar, pad_emu=pad)


class DesignRules:
    """Ответы дизайн-системы, которые нужны вёрстке, в одном месте.

    Один объект на прогон: `fit`, писатель pptx и html спрашивают одно и то же, и ответ
    обязан совпадать — иначе вписанный кегль разойдётся с записанным.
    """

    def __init__(self, manifest: TemplateManifest, design_system: DesignSystem | None = None):
        self.manifest = manifest
        #: Нет в состоянии (старый чекпойнт, вызов вне графа) — считается здесь же:
        #: `derive` — чистая функция без модели и файлов, миллисекунды (DG2).
        self.ds = design_system if design_system is not None else derive(manifest)

    # --- цвет ---------------------------------------------------------------------

    @property
    def roles_measured(self) -> bool:
        """Нашла ли дизайн-система по примерам хоть один акцент."""
        return any(role.role is ColorRoleKind.ACCENT for role in self.ds.palette_roles)

    def _slot_of(self, color_hex: str) -> ColorRef:
        """Слот темы, которым записать измеренный цвет.

        Ближайший по цвету, а среди равно близких — акцентный: у шаблонов кейса один
        и тот же синий лежит и в `dk2`, и в `accent1`, и называть акцент слотом тёмного
        текста значит спутать роль, хотя цвет тот же.
        """
        colors = self.manifest.theme.colors
        distance = {ref: delta_e_rgb(colors.get(ref), color_hex) for ref in ColorRef}
        best = min(distance.values())
        nearest = [ref for ref in ColorRef if distance[ref] == best]
        return next((ref for ref in nearest if ref in ACCENT_SLOTS), nearest[0])

    def accents(self) -> list[ColorRef]:
        """Акценты по убыванию роли: сначала измеренные по площади, затем слоты темы.

        Повторы по цвету выбрасываются: шесть слотов одного цвета — это один акцент.
        """
        colors = self.manifest.theme.colors
        measured = sorted(
            (role for role in self.ds.palette_roles if role.role is ColorRoleKind.ACCENT),
            key=lambda role: -role.share,
        )
        out: list[ColorRef] = []
        seen: set[str] = set()
        for ref in [*(self._slot_of(role.color_hex) for role in measured), *ACCENT_SLOTS]:
            color = colors.get(ref).upper()
            if color not in seen:
                seen.add(color)
                out.append(ref)
        return out

    def accent(
        self,
        background_hex: str | None,
        *,
        index: int = 0,
        kind: TextClass = TextClass.GRAPHICS,
        size_pt: float | None = None,
        bold: bool = False,
    ) -> ColorRef:
        """Акцент по роли дизайн-системы, который виден на этом фоне.

        `index` — какой по счёту акцент (у callout «риск» — второй). Акцент, который
        на фоне не берёт свой порог (`designsystem.contrast`, тот же, что у аудита),
        уступает следующему; не берёт никто — слот темы, ближайший к нужному по цвету
        и читаемый, а если нет и такого — первый по роли, как есть.
        """
        ordered = self.accents()
        start = index % len(ordered)
        pool = [*ordered[start:], *ordered[:start]]
        if background_hex is None:
            return pool[0]
        colors = self.manifest.theme.colors
        for ref in pool:
            color = colors.get(ref)
            if color.upper() == background_hex.upper():
                continue
            if readability(color, background_hex, kind, size_pt=size_pt, bold=bold).passes:
                return ref
        chosen = readable_ref(
            self.manifest.theme, background_hex, kind, prefer_hex=colors.get(pool[0])
        )
        return chosen or pool[0]

    def accent_ink(
        self, ref: ColorRef, background_hex: str | None, *, size_pt: float, bold: bool
    ) -> ColorRef | None:
        """Слот, которым набрать текст цвета акцента: сам акцент, если он читается
        как текст этого кегля, иначе тот же цвет глубже (правило заказчика из
        `designsystem.contrast`). Нет и такого — `None`: текст берёт цвет текста слайда."""
        if background_hex is None:
            return ref
        colors = self.manifest.theme.colors
        kind = text_class(size_pt, bold=bold)
        if readability(colors.get(ref), background_hex, kind, size_pt=size_pt, bold=bold).passes:
            return ref
        return readable_ref(
            self.manifest.theme, background_hex, kind, prefer_hex=colors.get(ref)
        )

    def block_accent(self, background_hex: str | None, *, size_pt: float | None = None) -> ColorRef:
        """Цвет по умолчанию у показателя, схемы и иконки, когда IR слота не назвал.

        Роли не измерены — `accent1`, как было до этого change (правило 10). Измерены —
        акцент по роли: у текста показателя свой порог крупного текста, у заливки узла
        и линии иконки — порог графики.
        """
        if not self.roles_measured:
            return ColorRef.ACCENT1
        kind = TextClass.GRAPHICS if size_pt is None else TextClass.LARGE
        return self.accent(background_hex, kind=kind, size_pt=size_pt)

    def background_hex(self, layout_id: str) -> str | None:
        """Фон, на котором стоит слайд: фон макета, иначе фон шаблона по примерам.

        Ни того ни другого — `None`, и выбор цвета идёт без проверки контраста: мерить
        не по чему, а подставлять «белый по умолчанию» значит выдумать фон.
        """
        layout = self.manifest.layout(layout_id)
        if layout is not None and layout.background is not None:
            return layout.background.color_hex
        for role in self.ds.palette_roles:
            if role.role is ColorRoleKind.BACKGROUND:
                return role.color_hex
        return None

    # --- кегль числа --------------------------------------------------------------

    def kpi_sizes(self) -> KpiSizes | None:
        """Кегли показателя по дизайн-системе; `None` — работает прежнее правило шкалы.

        Кегль числа в шаблоне берётся с его KPI-примера и лежит вне шкалы (у шаблонов
        кейса 32, 36, 66 pt), поэтому он приводится к ближайшей ступени шкалы — правило 6.

        Страховка от регрессии B13 (#139, показатель мельче списка рядом): ступень числа
        обязана быть крупнее основного текста. Не крупнее — измерение не годится (у VK Tech
        второй KPI-пример набран 8 pt на слайде другого размера), и показатель верстается
        прежним правилом, а `cold_notes` это называет.
        """
        sizes = self.ds.number_sizes
        ladder = self.manifest.size_ladder_pt
        if sizes.origin is not Origin.MEASURED or sizes.large_pt is None or not ladder:
            return None
        large = sizes.large_pt
        value = min(ladder, key=lambda step: (abs(step - large), -step))
        body = self.manifest.typography(TextRole.BODY)
        if body is not None and value <= body.size_pt:
            return None
        return KpiSizes(value_pt=value, small_pt=sizes.small_pt, measured_pt=large)

    # --- пропорции ----------------------------------------------------------------

    def tile(self) -> ComponentCard | None:
        """Плитка шаблона — первая в каталоге дизайн-системы: он уже упорядочен
        по представительности (число слайдов, затем площадь)."""
        return next(
            (card for card in self.ds.components if card.kind is ComponentKind.TILE), None
        )

    # --- цитата и callout ---------------------------------------------------------

    def _synth(self, kind: str) -> SynthElement | None:
        return next((item for item in self.ds.synthesized if item.kind == kind), None)

    def _role_pt(self, role: TextRole) -> float:
        step = self.manifest.typography(role) or self.manifest.typography(TextRole.BODY)
        if step is not None:
            return step.size_pt
        ladder = self.manifest.size_ladder_pt
        return ladder[-1] if ladder else 1.0

    def _boxed(self, element: SynthElement | None, role: TextRole, label: str) -> BoxedStyle:
        base = self.ds.grid.spacing.base_emu
        text_pt = (element.size_pt if element is not None else None) or self._role_pt(role)
        caption_pt = self._role_pt(TextRole.CAPTION)
        spacing = (element.spacing_emu if element is not None else None) or base
        line = (element.line_emu if element is not None else None) or max(1, base // 2)
        return BoxedStyle(
            role=role,
            text_pt=text_pt,
            minor_pt=min(caption_pt, text_pt),
            label=label,
            spacing_emu=spacing,
            line_emu=line,
        )

    def quote_style(self) -> BoxedStyle:
        """Цитата: кегль подзаголовка, полоса и отбивка — из элемента `quote` ДС."""
        return self._boxed(self._synth("quote"), TextRole.SUBTITLE, "")

    def callout_style(self, tone: CalloutTone) -> BoxedStyle:
        """Callout: кегль основного текста и подпись вида — из элемента ДС этого вида."""
        element = self._synth(_CALLOUT_KIND[tone])
        return self._boxed(element, TextRole.BODY, element.text if element is not None else "")

    def callout_accent(self, tone: CalloutTone, background_hex: str | None) -> ColorRef:
        return self.accent(background_hex, index=_CALLOUT_ACCENT[tone])

    # --- заметки прогона ----------------------------------------------------------

    def cold_notes(self) -> list[str]:
        """Что дизайн-система не измерила и где поэтому осталось прежнее правило."""
        notes: list[str] = []
        if not self.roles_measured:
            notes.append(
                "дизайн-система: роли цветов по слайдам-примерам не измерены "
                f"(примеров в шаблоне: {len(self.manifest.examples)}) — акцент блоков "
                "по порядку слотов темы, как прежде"
            )
        sizes = self.ds.number_sizes
        if sizes.origin is not Origin.MEASURED or sizes.large_pt is None:
            notes.append(
                "дизайн-система: кегль числа не измерен — в шаблоне нет показателя; "
                "показатели верстаются прежним правилом шкалы"
            )
        elif self.kpi_sizes() is None:
            notes.append(
                f"дизайн-система: кегль числа шаблона {sizes.large_pt:g} pt ложится на ступень "
                "шкалы не крупнее основного текста — показатели верстаются прежним правилом "
                "шкалы, иначе число вышло бы мельче списка рядом (B13)"
            )
        return notes
