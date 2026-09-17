#!/usr/bin/env python3
"""Замер детерминированного аудита на колоде из макетов шаблона. Запрос из #26.

Зачем отдельный скрипт, а не разовая проба: цифры калибровки (208 находок → 71, 3.5 → 1.2
на слайд) приводятся в `AUDIT.md` и в proposal change «audit-calibration». Замер, который
нельзя повторить одной командой, через неделю никто не повторит — и цифры превратятся
в предание.

    python scripts/bench_audit_calibration.py tests/fixtures/templates
    python scripts/bench_audit_calibration.py шаблон.pptx --per-check --out замер.json

Колода строится из **макетов манифеста**: по слайду на макет, заголовок и два буллета
в плейсхолдеры, тексты разные на каждом слайде. Она нарочно бедная — это замер области
проверок, а не качества генерации. Судить по ней о порогах плотности нельзя: слайд
с заголовком и двумя буллетами занимает меньше четверти площади на любом шаблоне.

Текст намеренно без чисел: иначе `content.numbers_grounded` справедливо ругался бы
на числа, которых нет в контент-пакете, и замер мерил бы подделку контента.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.audit.runner import AuditRunner
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import Severity, TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, DeckIR, SlideIR, TextBlock
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.export.pptx import export_pptx
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from deckforge.rendering.writer import WriterError

#: Плейсхолдеры, в которые текст не кладут (те же, что у писателя, change 13).
NON_TEXT = frozenset({"PIC", "CHART", "TBL", "MEDIA", "CLIPART", "DGM", "SLDIMG"})

TITLES = [
    "Спрос сместился в сторону готовых решений",
    "Ручная сборка перестала окупаться",
    "Команда выигрывает на скорости, а не на объёме",
    "Партнёры просят предсказуемых сроков",
    "Узкое место — согласование, а не разработка",
]
BULLETS = [
    "Сроки согласования сократились вдвое",
    "Клиенты приходят с готовым техническим заданием",
    "Поддержка закрывает обращения в день поступления",
    "Новые команды подключаются без отдельного обучения",
]


def texts_for(index: int) -> tuple[str, list[str]]:
    """Разный текст на каждом слайде: одинаковый дал бы находку про дубли."""
    return TITLES[index % len(TITLES)], [
        BULLETS[index % len(BULLETS)],
        BULLETS[(index + 1) % len(BULLETS)],
    ]


def text_placeholders(layout: LayoutSpec) -> tuple[int | None, int | None]:
    """Индексы плейсхолдеров заголовка и тела, если они у макета есть."""
    title = next(
        (p.idx for p in layout.placeholders if p.role is TextRole.TITLE), None
    )
    body = next(
        (
            p.idx
            for p in layout.placeholders
            if p.role is not TextRole.TITLE and p.ph_type not in NON_TEXT
        ),
        None,
    )
    return title, body


def build_deck(
    manifest: TemplateManifest, fonts: FontLibrary | None
) -> tuple[DeckIR, list[str]]:
    """По слайду на макет. Макет без текстовых плейсхолдеров пропускается с причиной."""
    slides: list[SlideIR] = []
    skipped: list[str] = []

    for index, layout in enumerate(manifest.layouts):
        title_idx, body_idx = text_placeholders(layout)
        if title_idx is None and body_idx is None:
            skipped.append(f"{layout.layout_id}: нет текстовых плейсхолдеров")
            continue

        headline, items = texts_for(index)
        blocks: list[TextBlock | BulletsBlock] = []
        if title_idx is not None:
            blocks.append(
                TextBlock(
                    block_id="t", placeholder_idx=title_idx, role=TextRole.TITLE, text=headline
                )
            )
        if body_idx is not None:
            blocks.append(
                BulletsBlock(
                    block_id="b",
                    placeholder_idx=body_idx,
                    role=TextRole.BODY,
                    items=[BulletItem(text=item) for item in items],
                )
            )

        slide = SlideIR(
            slide_id=f"s{len(slides) + 1:02d}",
            layout_id=layout.layout_id,
            variant="A",
            blocks=blocks,
        )
        try:
            slides.append(fit_slide(slide, manifest, fonts=fonts))
        except LayoutFitError as error:
            skipped.append(f"{layout.layout_id}: не вписан ({error})")

    deck = DeckIR(
        deck_id=manifest.source_name,
        variant="A",
        template_id=manifest.template_id,
        seed=1337,
        slides=slides,
    )
    return deck, skipped


@dataclass(slots=True)
class Measurement:
    template: str
    slides: int
    findings: int
    errors: int
    by_check: Counter[str] = field(default_factory=Counter)
    skipped_checks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def per_slide(self) -> float:
        return self.findings / self.slides if self.slides else 0.0

    @property
    def errors_per_slide(self) -> float:
        return self.errors / self.slides if self.slides else 0.0


def measure(path: Path, fonts: FontLibrary | None, cache: Path | None) -> Measurement:
    manifest = TemplateParser(cache_dir=cache).parse(path)
    deck, notes = build_deck(manifest, fonts)
    content = ContentPackage(
        brief=Brief(
            purpose="report", audience="внутренняя команда", target_slides=len(deck.slides) or 1
        )
    )

    deck_path: Path | None = None
    with tempfile.TemporaryDirectory() as work:
        if deck.slides:
            try:
                # Файл нужен проверкам, которые читают готовый .pptx (шрифты, палитра).
                # LibreOffice для этого не требуется — только для pdf и превью.
                deck_path = export_pptx(
                    deck, manifest, path, Path(work) / "deck.pptx", content=content
                )
            except (WriterError, ValueError) as error:
                notes.append(f"файл не записан ({error}) — проверки по .pptx будут пропущены")

        runner = AuditRunner()
        report = asyncio.run(
            runner.run(deck, manifest, content, deck_path=deck_path)
        ) if deck.slides else None

    if report is None:
        return Measurement(path.name, 0, 0, 0, notes=[*notes, "колода пуста: мерить нечего"])

    return Measurement(
        template=path.name,
        slides=len(deck.slides),
        findings=len(report.findings),
        errors=len(report.of_severity(Severity.ERROR)),
        by_check=Counter(f.check_id for f in report.findings),
        skipped_checks=sorted(runner.skipped_checks),
        notes=notes,
    )


def templates_in(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(p for p in source.rglob("*") if p.suffix.lower() in {".pptx", ".potx"})


def report(measurements: list[Measurement], per_check: bool) -> None:
    print(f"\n{'шаблон':<28} {'слайдов':>8} {'находок':>8} {'на слайд':>9} {'ошибок/слайд':>13}")
    print("-" * 70)
    for m in measurements:
        print(
            f"{m.template:<28} {m.slides:>8} {m.findings:>8} "
            f"{m.per_slide:>9.2f} {m.errors_per_slide:>13.2f}"
        )

    slides = sum(m.slides for m in measurements)
    findings = sum(m.findings for m in measurements)
    errors = sum(m.errors for m in measurements)
    print("-" * 70)
    print(
        f"{'итого':<28} {slides:>8} {findings:>8} "
        f"{findings / slides if slides else 0:>9.2f} {errors / slides if slides else 0:>13.2f}"
    )

    if per_check:
        total: Counter[str] = Counter()
        for m in measurements:
            total.update(m.by_check)
        print("\nпо проверкам:")
        for check_id, count in total.most_common():
            print(f"  {count:>5}  {check_id}")

    # Пропуск — не прохождение (change 15). Если не назвать, замер выглядит чище, чем есть.
    skipped = sorted({c for m in measurements for c in m.skipped_checks})
    if skipped:
        print(f"\nпроверки, которым нечего было смотреть ({len(skipped)}):")
        for check_id in skipped:
            print(f"  {check_id}")
    for m in measurements:
        for note in m.notes:
            print(f"  ! {m.template}: {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("templates", type=Path, help="Файл .pptx/.potx или каталог с ними")
    parser.add_argument("--per-check", action="store_true", help="Разбивка по проверкам")
    parser.add_argument("--out", type=Path, help="Куда сложить результат в json")
    parser.add_argument("--cache", type=Path, help="Каталог кэша манифестов")
    args = parser.parse_args()

    paths = templates_in(args.templates)
    if not paths:
        print(f"в {args.templates} нет ни одного .pptx/.potx", file=sys.stderr)
        return 1

    fonts = FontLibrary.default()
    measurements = [measure(path, fonts, args.cache) for path in paths]
    report(measurements, args.per_check)

    if args.out:
        args.out.write_text(
            json.dumps(
                [
                    {
                        "template": m.template,
                        "slides": m.slides,
                        "findings": m.findings,
                        "errors": m.errors,
                        "per_slide": round(m.per_slide, 3),
                        "errors_per_slide": round(m.errors_per_slide, 3),
                        "by_check": dict(m.by_check),
                        "skipped_checks": m.skipped_checks,
                        "notes": m.notes,
                    }
                    for m in measurements
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nнаписано {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
