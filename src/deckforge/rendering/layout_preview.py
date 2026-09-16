"""Превью макетов настоящим рендером. Change (6) `template-preview-render`.

Реализует тот же протокол `LayoutPreviewProvider`, что и схема из слоя `parsing`,
поэтому классификатор макетов не знает, чем ему нарисовали картинку.

Поставщики **дополняют друг друга, а не заменяют**. Это выяснилось на живом прогоне:
пустой макет рендерится белой страницей, потому что незаполненные плейсхолдеры в
PowerPoint не видны — рендер показывает оформление шаблона и **скрывает** структуру,
схема показывает структуру и не знает про оформление.

Поэтому основной поставщик здесь — `CompositePreview`: фон и декор берутся из рендера,
места под контент дорисовываются поверх. Классификатор видит и то и другое.

Конвертация 37 макетов занимает секунды, но требует LibreOffice в образе, поэтому вся
колода макетов рендерится **один раз** при первом обращении.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.parsing.layout_preview import SchematicPreview
from deckforge.rendering.layout_deck import build_layout_deck
from deckforge.rendering.soffice import SofficeRenderer, SofficeUnavailableError


class SofficePreview:
    """Рендер макетов через LibreOffice с ленивой отрисовкой всей колоды разом."""

    def __init__(
        self,
        template: Path,
        manifest: TemplateManifest,
        work_dir: Path,
        renderer: SofficeRenderer | None = None,
        only: Collection[str] | None = None,
    ) -> None:
        self.template = template
        self.manifest = manifest
        self.work_dir = work_dir
        self.renderer = renderer or SofficeRenderer()
        #: Какие макеты вообще рендерить. Обычно это спорные для эвристики: конвертировать
        #: весь шаблон ради десятка вопросов модели не окупается (см. build_layout_deck).
        self.only = only
        self._pages: dict[str, bytes] | None = None

    @property
    def available(self) -> bool:
        return self.renderer.available

    def render(self, layout: LayoutSpec, slide_cx: int, slide_cy: int) -> bytes:
        """Картинка макета. Первый вызов конвертирует всю колоду, дальше — из памяти."""
        if self._pages is None:
            self._pages = self._render_all()
        page = self._pages.get(layout.layout_id)
        if page is None:
            raise SofficeUnavailableError(
                f"для макета {layout.layout_id} не получено превью"
            )
        return page

    def _render_all(self) -> dict[str, bytes]:
        deck = self.work_dir / "layouts.pptx"
        order = build_layout_deck(self.template, self.manifest, deck, only=self.only)
        pages = self.renderer.to_pngs(deck, self.work_dir)

        if len(pages) != len(order):
            # Несовпадение числа страниц и макетов означает, что соответствие уехало.
            # Молча отдать не тот макет хуже, чем не отдать ничего.
            raise SofficeUnavailableError(
                f"страниц {len(pages)}, а макетов {len(order)}: соответствие ненадёжно"
            )
        return {order[i]: page.read_bytes() for i, page in enumerate(pages)}

    def save_previews(self, out_dir: Path) -> dict[str, Path]:
        """Разложить превью по файлам и вернуть пути — для `LayoutSpec.preview_png` и UI."""
        if self._pages is None:
            self._pages = self._render_all()
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: dict[str, Path] = {}
        for layout_id, blob in self._pages.items():
            path = out_dir / f"{layout_id}.png"
            path.write_bytes(blob)
            saved[layout_id] = path
        return saved


class CompositePreview:
    """Рендер шаблона плюс дорисованные поверх места под контент.

    Ни один из поставщиков по отдельности не даёт классификатору полной картины:

    * рендер показывает фон, логотип и плашки шаблона, но пустые плейсхолдеры в нём
      невидимы — у макетов без декора все страницы выходят одинаково белыми;
    * схема показывает плейсхолдеры, но ничего не знает про оформление.

    Здесь одно кладётся на другое. Если LibreOffice недоступен или макет не отрисовался,
    остаётся схема: превью без декора хуже полного, но лучше отсутствующего.
    """

    def __init__(
        self,
        template: Path,
        manifest: TemplateManifest,
        work_dir: Path,
        renderer: SofficeRenderer | None = None,
        opacity: float = 0.55,
        only: Collection[str] | None = None,
    ) -> None:
        self.soffice = SofficePreview(template, manifest, work_dir, renderer, only=only)
        self.schematic = SchematicPreview()
        #: Плейсхолдеры полупрозрачны: под ними должно оставаться видно фон шаблона,
        #: иначе теряется ровно та информация, ради которой затевался рендер.
        self.opacity = opacity
        self.fallbacks = 0

    def render(self, layout: LayoutSpec, slide_cx: int, slide_cy: int) -> bytes:
        try:
            background = self.soffice.render(layout, slide_cx, slide_cy)
        except Exception:
            self.fallbacks += 1
            return self.schematic.render(layout, slide_cx, slide_cy)

        overlay = self.schematic.render(layout, slide_cx, slide_cy)
        return _blend(background, overlay, self.opacity)


def _blend(background_png: bytes, overlay_png: bytes, opacity: float) -> bytes:
    """Наложить схему на рендер, подогнав её под размер страницы."""
    import io

    from PIL import Image

    base = Image.open(io.BytesIO(background_png)).convert("RGB")
    over = Image.open(io.BytesIO(overlay_png)).convert("RGB").resize(base.size)
    merged = Image.blend(base, over, opacity)

    buffer = io.BytesIO()
    merged.save(buffer, format="PNG")
    return buffer.getvalue()
