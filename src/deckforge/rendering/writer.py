"""`SlideIR` → .pptx. Change (13) `pptx-writer`.

Инварианты рендерера (ADR-002):
* слайд создаётся **только** на макете из шаблона — по части пакета, а не по позиции
  в `prs.slide_layouts` (там только первый мастер и другой порядок, см. proposal change 13);
* текст кладётся в плейсхолдеры, а не в новые текстбоксы, где плейсхолдер есть;
* цвет задаётся ссылкой на тему (`MSO_THEME_COLOR`), не литеральным RGB;
* кегль берётся из `manifest.typography_scale` через `fit_report`, не подбирается на глаз.
Любой литерал RGB/шрифта/EMU в этом модуле — ошибка линтера `lint_no_template_constants`.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image, UnidentifiedImageError
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from deckforge.domain.base import BBox
from deckforge.domain.content import ContentPackage
from deckforge.domain.enums import ImageSource
from deckforge.domain.slide import BulletsBlock, DeckIR, ImageBlock, SlideIR, TextBlock
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.parsing.ooxml.layouts import resolve_placeholders
from deckforge.parsing.package import TemplatePackage
from deckforge.rendering.images import add_image
from deckforge.rendering.theme_binding import apply_theme_color, theme_font_token

#: Плейсхолдеры, в которые текст не кладётся: там ждут картинку, диаграмму, таблицу.
_NON_TEXT_PLACEHOLDERS = frozenset({"PIC", "CHART", "TBL", "MEDIA", "CLIPART", "DGM", "SLDIMG"})

#: Какой change добавит блок, который писатель пока не умеет.
_PENDING_BLOCKS = {
    "chart": "(14) native-charts-tables",
    "table": "(14) native-charts-tables",
    "kpi": "(14) native-charts-tables",
    "smartart": "(21) smartart-icons",
    "icon": "(21) smartart-icons",
}

_CONTENT_TYPE_POTX = "presentationml.template.main+xml"
_CONTENT_TYPE_PPTX = "presentationml.presentation.main+xml"
_PARAGRAPH_BREAK = re.compile(r"\r\n|[\n\r]")


class WriterError(ValueError):
    """IR нельзя записать, не нарушив инвариантов. Файл при этом не создаётся."""


def _open_template(path: Path) -> object:
    """python-pptx не открывает .potx: подменяем content type главной части в памяти."""
    data = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        types = zin.read("[Content_Types].xml").decode("utf-8")
        if _CONTENT_TYPE_POTX not in types:
            return Presentation(io.BytesIO(data))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                payload = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    payload = types.replace(_CONTENT_TYPE_POTX, _CONTENT_TYPE_PPTX).encode("utf-8")
                zout.writestr(item, payload)
    buffer.seek(0)
    return Presentation(buffer)


def _drop_sample_slides(prs: object) -> None:
    """Слайды-примеры шаблона в колоду не попадают; части без связей python-pptx не пишет.

    Произвольные показы и разделы ссылаются на слайды-примеры: без них ссылки повисли бы,
    и PowerPoint предложил бы «восстановить» файл. К новой колоде они отношения не имеют.
    """
    presentation = prs.part._element  # type: ignore[attr-defined]
    for node in presentation.findall(qn("p:custShowLst")):
        presentation.remove(node)
    for ext in presentation.findall(f"{qn('p:extLst')}/{qn('p:ext')}"):
        if any(etree.QName(child).localname == "sectionLst" for child in ext):
            ext.getparent().remove(ext)

    slide_ids = prs.slides._sldIdLst  # type: ignore[attr-defined]
    for slide_id in list(slide_ids):
        prs.part.drop_rel(slide_id.rId)  # type: ignore[attr-defined]
        slide_ids.remove(slide_id)


def _paragraphs(block: TextBlock | BulletsBlock) -> list[tuple[str, int]]:
    if isinstance(block, TextBlock):
        return [(text, 0) for text in _PARAGRAPH_BREAK.split(block.text)]
    return [(item.text, item.level) for item in block.items]


class PptxWriter:
    def __init__(self, template_path: Path, manifest: TemplateManifest) -> None:
        self.template_path = template_path
        self.manifest = manifest

    # --- проверка ------------------------------------------------------------

    def validate(self, slide: SlideIR, content: ContentPackage | None = None) -> None:
        """Инварианты §4.4: макет есть в манифесте, placeholder_idx существует,
        координаты внутри полей, цвета — только `color_ref`, текст вписан."""
        problems = self._problems(slide, content)
        if problems:
            raise WriterError("\n".join(problems))

    def _problems(self, slide: SlideIR, content: ContentPackage | None) -> list[str]:
        layout = self.manifest.layout(slide.layout_id)
        if layout is None:
            return [f"{slide.slide_id}: макета {slide.layout_id} нет в манифесте"]
        if not slide.blocks:
            # Такой слайд — пустой фон шаблона; живой прогон показал, что без проверки
            # он молча попадает в колоду.
            return [f"{slide.slide_id}: слайд без блоков"]
        out: list[str] = []
        if all(isinstance(block, ImageBlock) for block in slide.blocks):
            out.append(f"{slide.slide_id}: слайд из одних картинок нарушает C3")
        taken: set[int] = set()
        for block in slide.blocks:
            where = f"{slide.slide_id}/{block.block_id}"
            idx = getattr(block, "placeholder_idx", None)
            if idx is not None:
                if idx in taken:
                    out.append(f"{where}: плейсхолдер idx={idx} уже занят другим блоком")
                taken.add(idx)
            if block.type in _PENDING_BLOCKS:
                pending = _PENDING_BLOCKS[block.type]
                out.append(f"{where}: блок {block.type} добавит change {pending}")
            elif isinstance(block, TextBlock | BulletsBlock):
                out += self._text_problems(where, block, layout, slide)
            elif isinstance(block, ImageBlock):
                out += self._image_problems(where, block, content)
        return out

    def _text_problems(
        self, where: str, block: TextBlock | BulletsBlock, layout: LayoutSpec, slide: SlideIR
    ) -> list[str]:
        out: list[str] = []
        texts = [block.text] if isinstance(block, TextBlock) else [i.text for i in block.items]
        if not any(text.strip() for text in texts):
            out.append(f"{where}: пустой текст — на слайде осталось бы «Введите текст»")
        if block.placeholder_idx is not None and block.bbox is not None:
            out.append(f"{where}: заданы и плейсхолдер, и координаты — координаты потерялись бы")
        if block.placeholder_idx is not None:
            placeholder = layout.placeholder(block.placeholder_idx)
            if placeholder is None:
                out.append(
                    f"{where}: в макете {layout.layout_id} нет плейсхолдера "
                    f"idx={block.placeholder_idx}"
                )
            elif placeholder.ph_type in _NON_TEXT_PLACEHOLDERS:
                out.append(f"{where}: текст в плейсхолдер {placeholder.ph_type}")
        elif block.bbox is None:
            out.append(f"{where}: нет ни плейсхолдера, ни координат")
        elif not self.manifest.content_bbox.contains(block.bbox):
            out.append(f"{where}: координаты выходят за поля шаблона")

        fit = slide.fit_report.get(block.block_id)
        ladder = self.manifest.size_ladder_pt
        if fit is None:
            out.append(f"{where}: нет записи в fit_report — вписывание не выполнялось")
        else:
            if fit.overflow:
                out.append(f"{where}: переполнение, стратегия {fit.strategy}")
            if ladder and fit.final_size_pt not in ladder:
                out.append(f"{where}: кегль {fit.final_size_pt:g} вне шкалы шаблона {ladder}")
        return out

    def _image_problems(
        self, where: str, block: ImageBlock, content: ContentPackage | None
    ) -> list[str]:
        out: list[str] = []
        if block.bbox is None:
            out.append(f"{where}: картинка без координат")
        elif not self.manifest.slide_size.bbox.contains(block.bbox):
            # Картинке можно во весь слайд — «фото на весь слайд» обычный макет, — но не за край.
            out.append(f"{where}: картинка выходит за слайд")
        if block.source is ImageSource.GENERATED:
            out.append(f"{where}: сгенерированные картинки добавит change (24) image-generation")
        elif content is None or content.asset(block.asset_ref or "") is None:
            out.append(f"{where}: ассета {block.asset_ref} нет в ContentPackage")
        else:
            asset = content.asset(block.asset_ref or "")
            if asset is not None and not Path(asset.path).is_file():
                out.append(f"{where}: файл ассета не найден: {asset.path}")
            elif asset is not None:
                try:
                    with Image.open(asset.path) as image:
                        image.verify()
                except (UnidentifiedImageError, OSError):
                    out.append(f"{where}: ассет {asset.path} не картинка")
        return out

    # --- запись --------------------------------------------------------------

    def write(
        self, deck: DeckIR, out_path: Path, content: ContentPackage | None = None
    ) -> Path:
        if deck.template_id != self.manifest.template_id:
            raise WriterError(
                f"template_id колоды {deck.template_id} не совпадает с манифестом "
                f"{self.manifest.template_id}"
            )
        problems = [p for slide in deck.slides for p in self._problems(slide, content)]
        if problems:
            raise WriterError("\n".join(problems))

        prs = _open_template(self.template_path)
        _drop_sample_slides(prs)
        layouts = self._layouts_by_id(prs)
        for slide in deck.slides:
            self._render_slide(prs, layouts[slide.layout_id], slide, content)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(out_path))  # type: ignore[attr-defined]
        return out_path

    def _layouts_by_id(self, prs: object) -> dict[str, object]:
        """`layout_id` → макет python-pptx через имя части пакета.

        Порядок `LayoutSpec.index` восстанавливается тем же обходом, что в парсере; имя макета
        сверяется, чтобы расхождение обходов или манифест от другого файла не положили слайд
        на чужой макет молча.
        """
        with TemplatePackage(self.template_path) as pkg:
            parts: list[tuple[str, str]] = []
            for master in pkg.master_parts():
                master_xml = pkg.read(master)
                for part in pkg.layout_parts(master):
                    if pkg.has(part) and resolve_placeholders(pkg.read(part), master_xml):
                        parts.append((part, pkg.layout_name(part)))

        by_part = {
            str(layout.part.partname).lstrip("/"): layout
            for master in prs.slide_masters  # type: ignore[attr-defined]
            for layout in master.slide_layouts
        }
        out: dict[str, object] = {}
        for spec in self.manifest.layouts:
            if spec.index >= len(parts):
                raise WriterError(f"макет {spec.layout_id}: в шаблоне нет макета №{spec.index}")
            part, name = parts[spec.index]
            if name.strip() == spec.name and part not in by_part:
                raise WriterError(
                    f"макет {spec.layout_id} «{spec.name}» есть в связях мастера, "
                    "но не в его списке макетов — PowerPoint его не покажет"
                )
            if name.strip() != spec.name:
                raise WriterError(
                    f"макет {spec.layout_id} «{spec.name}» не найден в шаблоне: на его месте "
                    f"«{name.strip()}» — манифест снят не с этого файла?"
                )
            out[spec.layout_id] = by_part[part]
        return out

    def _render_slide(
        self, prs: object, layout: object, slide_ir: SlideIR, content: ContentPackage | None
    ) -> None:
        slide = prs.slides.add_slide(layout)  # type: ignore[attr-defined]
        used: set[int] = set()
        for block in slide_ir.blocks:
            if isinstance(block, TextBlock | BulletsBlock):
                size_pt = slide_ir.fit_report[block.block_id].final_size_pt
                if block.placeholder_idx is not None:
                    self._fill_placeholder(slide, layout, block, size_pt)
                    used.add(block.placeholder_idx)
                else:
                    self._add_textbox(slide, block, size_pt)
            elif isinstance(block, ImageBlock) and content is not None:
                asset = content.asset(block.asset_ref or "")
                if asset is not None:
                    add_image(slide, block, Path(asset.path))

        # Пустой плейсхолдер в PowerPoint показывает «Введите текст» — такой слайд выглядит
        # недоделанным.
        for placeholder in list(slide.placeholders):
            if placeholder.placeholder_format.idx not in used:
                placeholder._element.getparent().remove(placeholder._element)

        if slide_ir.speaker_note:
            slide.notes_slide.notes_text_frame.text = slide_ir.speaker_note

    def _fill_placeholder(
        self, slide: object, layout: object, block: TextBlock | BulletsBlock, size_pt: float
    ) -> None:
        idx = block.placeholder_idx
        try:
            shape = slide.placeholders[idx]  # type: ignore[attr-defined]
        except KeyError:
            # Дату, футер и номер слайда python-pptx с макета не копирует — клонируем сами.
            source = next(
                (
                    ph for ph in layout.placeholders  # type: ignore[attr-defined]
                    if ph.placeholder_format.idx == idx
                ),
                None,
            )
            if source is None:
                # Парсер видит плейсхолдеры и внутри групп, python-pptx — только верхний уровень.
                raise WriterError(
                    f"плейсхолдер idx={idx} есть в манифесте, но недоступен в макете "
                    "(вложен в группу?)"
                ) from None
            slide.shapes.clone_placeholder(source)  # type: ignore[attr-defined]
            shape = slide.placeholders[idx]  # type: ignore[attr-defined]
        # Гарнитура не задаётся: её наследует плейсхолдер шаблона.
        color = block.color_ref if isinstance(block, TextBlock) else None
        self._write_paragraphs(shape.text_frame, _paragraphs(block), size_pt, color, None, None)

    def _add_textbox(self, slide: object, block: TextBlock | BulletsBlock, size_pt: float) -> None:
        box: BBox = block.bbox  # type: ignore[assignment]
        step = self.manifest.typography(block.role)
        shape = slide.shapes.add_textbox(  # type: ignore[attr-defined]
            Emu(box.x), Emu(box.y), Emu(box.cx), Emu(box.cy)
        )
        shape.text_frame.word_wrap = True
        # Текстбокс ничего не наследует: гарнитура и цвет — ссылками на тему из типошкалы.
        color = block.color_ref if isinstance(block, TextBlock) else None
        self._write_paragraphs(
            shape.text_frame,
            _paragraphs(block),
            size_pt,
            color or (step.color_ref if step else None),
            theme_font_token(step.font_ref) if step else None,
            step.bold if step else None,
        )

    @staticmethod
    def _write_paragraphs(
        text_frame: object,
        paragraphs: list[tuple[str, int]],
        size_pt: float,
        color: object,
        font_token: str | None,
        bold: bool | None,
    ) -> None:
        text_frame.clear()  # type: ignore[attr-defined]
        for i, (text, level) in enumerate(paragraphs):
            paragraph = (
                text_frame.paragraphs[0] if i == 0  # type: ignore[attr-defined]
                else text_frame.add_paragraph()  # type: ignore[attr-defined]
            )
            paragraph.text = text
            paragraph.level = level
            for run in paragraph.runs:
                # Кегль явно: рендер обязан совпасть с расчётом `layout`, а наследованный
                # кегль плейсхолдера может отличаться от кегля роли.
                run.font.size = Pt(size_pt)
                if color is not None:
                    apply_theme_color(run.font, color)  # type: ignore[arg-type]
                if font_token is not None:
                    run.font.name = font_token
                if bold is not None:
                    run.font.bold = bold
