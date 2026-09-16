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

from deckforge.domain.enums import ColorRef, LayoutKind
from deckforge.domain.template import (
    ChartDefaults,
    Decor,
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
from deckforge.parsing.ooxml.decor import extract_decor
from deckforge.parsing.ooxml.layouts import parse_shapes, resolve_placeholders
from deckforge.parsing.ooxml.theme import parse_theme
from deckforge.parsing.package import TemplatePackage
from deckforge.parsing.typography import (
    TypographyObservation,
    collect_observations,
    derive_scale,
)

PARSER_VERSION = "1.0.0"

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
        layouts, observations = self._read_layouts(pkg, masters, slide_size)
        if not layouts:
            raise ValueError("в шаблоне нет макетов с пригодными плейсхолдерами")

        typography = derive_scale(observations, theme)
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
            chart_defaults=ChartDefaults(series_color_refs=list(_SERIES_REFS)),
            parser_version=PARSER_VERSION,
        )

    def _read_theme(self, pkg: TemplatePackage, master_part: str) -> Theme:
        theme_part = pkg.theme_part(master_part)
        if theme_part is None or not pkg.has(theme_part):
            raise ValueError(f"у мастера {master_part} не найдена тема")
        return parse_theme(pkg.read(theme_part))

    def _read_layouts(
        self, pkg: TemplatePackage, masters: list[str], slide_size: SlideSize
    ) -> tuple[list[LayoutSpec], list[TypographyObservation]]:
        layouts: list[LayoutSpec] = []
        observations: list[TypographyObservation] = []
        index = 0

        for master_index, master_part in enumerate(masters, start=1):
            master_xml = pkg.read(master_part)
            master_id = f"M{master_index:02d}"

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
                    )
                )
                observations += collect_observations(
                    layout_xml, {p.idx: p.role for p in placeholders if p.role}
                )
                index += 1

        return layouts, observations

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
