"""pptx/potx → `TemplateManifest`. Change (3) `template-parsing-core` + (4) `theme-extraction`.

Единственная точка, где читается исходный файл шаблона (ADR-003). Всё, что находится выше
по пайплайну, работает с манифестом и про существование .pptx не знает.

Кэш по SHA-256: повторный парсинг того же файла — 0 с (бюджет §12).
"""

from __future__ import annotations

import hashlib
import json
from math import gcd
from pathlib import Path

from deckforge.domain.enums import ColorRef, LayoutKind, TextRole
from deckforge.domain.template import (
    ChartDefaults,
    Decor,
    LayoutBackground,
    LayoutCapacity,
    LayoutSpec,
    SlideSize,
    TemplateManifest,
    Theme,
    TypographyStep,
)
from deckforge.parsing.capacity import compute_capacity
from deckforge.parsing.grid import infer_grid
from deckforge.parsing.layout_kind import LayoutClassifier
from deckforge.parsing.ooxml.background import full_bleed_blip, parse_background
from deckforge.parsing.ooxml.bullets import parse_bullets
from deckforge.parsing.ooxml.decor import extract_decor
from deckforge.parsing.ooxml.layouts import parse_shapes, resolve_placeholders
from deckforge.parsing.ooxml.theme import parse_theme
from deckforge.parsing.package import TemplatePackage
from deckforge.parsing.typography import (
    TypographyObservation,
    collect_observations,
    derive_scale,
    observations_from_text_styles,
)

PARSER_VERSION = "1.4.0"  # 1.3.0 — маркер списка; 1.4.0 — его уровни

#: Цвета серий диаграмм по умолчанию: акценты темы в порядке схемы.
#: Благодаря этому диаграмма перекрашивается вместе со сменой шаблона (ADR-002).
_SERIES_REFS: tuple[ColorRef, ...] = (
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
)


#: Заглушка на время сборки: настоящая вместимость проставляется после вывода типошкалы,
#: потому что без кегля её не вычислить.
_EMPTY_CAPACITY = LayoutCapacity(max_bullets=0, max_chars_body=0, max_chars_title=0)


#: Ссылки на гарнитуры темы в OOXML. Плейсхолдер часто не называет шрифт прямо,
#: а ссылается на мажорную или минорную гарнитуру схемы.
_THEME_FONT_REFS = {
    "+mj-lt": "major_latin",
    "+mn-lt": "minor_latin",
    "+mj-cs": "major_cs",
    "+mn-cs": "minor_cs",
}


def _resolve_placeholder_fonts(layout: LayoutSpec, theme: Theme) -> LayoutSpec:
    """Развернуть ссылки вида `+mj-lt` в имя гарнитуры темы.

    Слоям выше не должно быть дела до синтаксиса OOXML: они спрашивают, каким шрифтом
    набран плейсхолдер, и получают имя, которое можно найти в системе.
    """
    updated = []
    changed = False
    for ph in layout.placeholders:
        slot = _THEME_FONT_REFS.get(ph.font_family or "")
        if slot is None:
            updated.append(ph)
            continue
        updated.append(ph.model_copy(update={"font_family": getattr(theme.fonts, slot)}))
        changed = True
    return layout.model_copy(update={"placeholders": updated}) if changed else layout


def template_id_of(path: Path) -> str:
    """`sha256:<hex>` — идентификатор шаблона и ключ кэша манифеста."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def aspect_of(cx: int, cy: int) -> str:
    """Соотношение сторон в виде «16:9». Считается, а не угадывается по размеру."""
    if cx <= 0 or cy <= 0:
        return "unknown"
    divisor = gcd(cx, cy)
    width, height = cx // divisor, cy // divisor
    # Пропорции вроде 12192000×6858000 сокращаются в 16:9 не сразу — нормализуем известные.
    for candidate_w, candidate_h in ((16, 9), (4, 3), (16, 10), (3, 2), (1, 1)):
        if abs(cx / cy - candidate_w / candidate_h) < 0.005:
            return f"{candidate_w}:{candidate_h}"
    return f"{width}:{height}"


class TemplateParser:
    """Сборка манифеста из пакета шаблона."""

    def __init__(
        self, cache_dir: Path | None = None, classifier: LayoutClassifier | None = None
    ) -> None:
        self.cache_dir = cache_dir
        #: Без VLM-клиента классификатор работает одной эвристикой — это рабочий режим,
        #: а не деградация: вид макета получают все макеты в любом случае.
        self.classifier = classifier or LayoutClassifier()

    # --- кэш ---------------------------------------------------------------

    def _cache_path(self, template_id: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{template_id.replace(':', '_')}.json"

    def load_cached(self, template_id: str) -> TemplateManifest | None:
        path = self._cache_path(template_id)
        if path is None or not path.exists():
            return None
        manifest = TemplateManifest.model_validate_json(path.read_text(encoding="utf-8"))
        # Манифест, снятый прежней версией парсера, кэшем не считается.
        return manifest if manifest.parser_version == PARSER_VERSION else None

    def save_cached(self, manifest: TemplateManifest) -> None:
        path = self._cache_path(manifest.template_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # --- разбор ------------------------------------------------------------

    def parse(self, path: Path, *, use_cache: bool = True) -> TemplateManifest:
        template_id = template_id_of(path)
        if use_cache and (cached := self.load_cached(template_id)) is not None:
            return cached

        with TemplatePackage(path) as pkg:
            manifest = self._build(pkg, template_id)

        if use_cache:
            self.save_cached(manifest)
        return manifest

    def _build(self, pkg: TemplatePackage, template_id: str) -> TemplateManifest:
        cx, cy = pkg.slide_size()
        slide_size = SlideSize(cx_emu=cx, cy_emu=cy, aspect=aspect_of(cx, cy))

        masters = pkg.master_parts()
        if not masters:
            raise ValueError("в шаблоне нет ни одного slideMaster")

        theme = self._read_theme(pkg, masters[0])
        layouts, observations = self._read_layouts(pkg, masters, slide_size, theme)
        if not layouts:
            raise ValueError("в шаблоне нет макетов с пригодными плейсхолдерами")

        typography = derive_scale(observations, theme)
        layouts = [_resolve_placeholder_fonts(layout, theme) for layout in layouts]
        layouts = self._fill_capacity(layouts, typography, cx * cy)
        layouts = self._classify(layouts, slide_size)

        return TemplateManifest(
            template_id=template_id,
            source_name=pkg.path.name,
            slide_size=slide_size,
            theme=theme,
            typography_scale=typography,
            grid=infer_grid(layouts, slide_size, pkg.read_optional("ppt/viewProps.xml")),
            layouts=layouts,
            decor=self._read_decor(pkg, masters[0], cx, cy),
            bullet_levels=parse_bullets(pkg.read(masters[0]), theme.colors),
            chart_defaults=ChartDefaults(series_color_refs=list(_SERIES_REFS)),
            parser_version=PARSER_VERSION,
        )

    def _read_theme(self, pkg: TemplatePackage, master_part: str) -> Theme:
        theme_part = pkg.theme_part(master_part)
        if theme_part is None or not pkg.has(theme_part):
            raise ValueError(f"у мастера {master_part} не найдена тема")
        return parse_theme(pkg.read(theme_part))

    def _read_layouts(
        self, pkg: TemplatePackage, masters: list[str], slide_size: SlideSize, theme: Theme
    ) -> tuple[list[LayoutSpec], list[TypographyObservation]]:
        layouts: list[LayoutSpec] = []
        observations: list[TypographyObservation] = []
        style_observations: list[TypographyObservation] = []
        index = 0

        for master_index, master_part in enumerate(masters, start=1):
            master_xml = pkg.read(master_part)
            master_id = f"M{master_index:02d}"
            master_roles: dict[int, TextRole] = {}

            for layout_part in pkg.layout_parts(master_part):
                if not pkg.has(layout_part):
                    continue
                layout_xml = pkg.read(layout_part)
                placeholders = resolve_placeholders(layout_xml, master_xml)
                if not placeholders:
                    # Макет без пригодных плейсхолдеров композиции не поможет.
                    continue

                layouts.append(
                    LayoutSpec(
                        layout_id=f"L{index:02d}",
                        name=pkg.layout_name(layout_part),
                        master=master_id,
                        part_name=layout_part,
                        index=index,
                        # Вид проставляется отдельным проходом: классификатору нужен
                        # собранный LayoutSpec, чтобы отрисовать превью.
                        kind=LayoutKind.CUSTOM,
                        kind_confidence=0.0,
                        kind_source="pending",
                        capacity=_EMPTY_CAPACITY,
                        placeholders=placeholders,
                        shapes=parse_shapes(
                            layout_xml, slide_size.cx_emu, slide_size.cy_emu
                        ),
                        background=self._read_background(
                            pkg,
                            (layout_part, layout_xml),
                            (master_part, master_xml),
                            theme,
                            slide_size,
                        ),
                    )
                )
                roles = {p.idx: p.role for p in placeholders if p.role}
                master_roles.update(roles)
                observations += collect_observations(layout_xml, roles)
                index += 1

            # Кегли бывают заданы не в макетах, а в самом мастере. Шаблоны, сделанные
            # не в PowerPoint, держат шкалу именно там: у них макет ссылается на мастер,
            # а не повторяет размеры. Без этого прохода такой шаблон вообще не парсится —
            # `derive_scale` получает пустой список и честно отказывается работать.
            # Наблюдения мастера идут после макетов: при равной частоте кегль,
            # объявленный в макете, остаётся более сильным сигналом.
            observations += collect_observations(master_xml, master_roles)
            style_observations += observations_from_text_styles(master_xml)

        # `txStyles` подключается только к ролям, которых не видно больше нигде.
        # Иначе стиль по умолчанию перебивал бы то, что шаблон объявил на фигурах явно,
        # а он в каскаде OOXML стоит ниже их.
        seen = {obs.role for obs in observations}
        observations += [obs for obs in style_observations if obs.role not in seen]

        return layouts, observations

    def _read_background(
        self,
        pkg: TemplatePackage,
        layout: tuple[str, bytes],
        master: tuple[str, bytes],
        theme: Theme,
        slide_size: SlideSize,
    ) -> LayoutBackground:
        """Фон макета с разрешённой подложкой.

        Картинка во весь слайд ищется сначала в макете, затем в мастере: мастер кладёт
        общую подложку, макет — свою поверх неё. Байты берутся из связей **той** части,
        в которой картинка нашлась: связь `rId1` в макете и в мастере ведёт к разным
        файлам, и перепутать их значит померить контраст по чужой картинке.
        """
        picture_bytes: bytes | None = None
        for part, xml in (layout, master):
            blip = full_bleed_blip(xml, slide_size)
            if blip is None:
                continue
            blobs, targets = pkg.media_of(part)
            picture_bytes = blobs.get(targets.get(blip, ""))
            if picture_bytes is not None:
                break
        return parse_background(layout[1], master[1], theme, picture_bytes=picture_bytes)

    def _fill_capacity(
        self, layouts: list[LayoutSpec], typography: list[TypographyStep], slide_area: int
    ) -> list[LayoutSpec]:
        """Вместимость считается после типошкалы: без кегля её не вычислить."""
        return [
            layout.model_copy(
                update={
                    "capacity": compute_capacity(layout.placeholders, typography, slide_area)
                }
            )
            for layout in layouts
        ]

    def _classify(self, layouts: list[LayoutSpec], slide_size: SlideSize) -> list[LayoutSpec]:
        """Вид макета: эвристика для всех, VLM — только для спорных (§5, ADR-004)."""
        classified: list[LayoutSpec] = []
        for layout in layouts:
            result = self.classifier.classify(layout.placeholders, slide_size, layout)
            classified.append(
                layout.model_copy(
                    update={
                        "kind": result.kind,
                        "kind_confidence": result.confidence,
                        "kind_source": result.source,
                    }
                )
            )
        return classified

    def _read_decor(
        self, pkg: TemplatePackage, master_part: str, cx: int, cy: int
    ) -> Decor:
        media, rel_targets = pkg.media_of(master_part)
        return extract_decor(
            pkg.read(master_part),
            master_id="M01",
            slide_cx=cx,
            slide_cy=cy,
            media=media,
            rel_targets=rel_targets,
        )
