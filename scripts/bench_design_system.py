#!/usr/bin/env python3
"""Замер дизайн-системы шаблона по его слайдам-примерам. Change `design-system-from-examples`.

Таблица из `docs/agents/tasks-design-system.md` снималась разовым скриптом, а замер,
который нельзя повторить одной командой, через неделю превращается в предание. Здесь
она воспроизводится из манифеста — то есть ровно из того, чем пользуется генерация.

    python scripts/bench_design_system.py tests/fixtures/templates
    python scripts/bench_design_system.py шаблон.pptx --out замер.json

Кегли приводятся к общему масштабу. Внутри одного шаблона они сравнимы как есть,
а между шаблонами — нет: у VK Tech слайд 10 × 5,62″ против 13,33 × 7,5″ у остальных,
и вся его типографика мельче ровно в 1,33 раза. Без приведения кегли 6,75 и 8,12 pt
выглядят особенностью дизайна, хотя это особенность размера слайда.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.domain.template import TemplateManifest
from deckforge.parsing import TemplateParser

#: Ширина слайда, к которой приводятся кегли разных шаблонов, — 13,33″ в EMU.
REFERENCE_SLIDE_CX = 12_192_000


@dataclass(slots=True)
class Measurement:
    """Строка таблицы: один шаблон."""

    name: str
    masters: int
    layouts: int
    examples: int
    layouts_with_examples: int
    shapes: int
    outside_placeholders: float
    theme_fonts: list[str]
    used_fonts: list[tuple[str, int]]
    palette: int
    sizes_pt: list[float]
    seconds: float
    slide_scale: float = 1.0
    notes: list[str] = field(default_factory=list)


def measure(path: Path) -> Measurement:
    started = time.perf_counter()
    manifest = TemplateParser().parse(path, use_cache=False)
    seconds = time.perf_counter() - started
    return _of_manifest(path.name, manifest, seconds)


def _of_manifest(name: str, manifest: TemplateManifest, seconds: float) -> Measurement:
    shapes = [shape for example in manifest.examples for shape in example.shapes]
    outside = [shape for shape in shapes if shape.placeholder_idx is None]
    scale = REFERENCE_SLIDE_CX / manifest.slide_size.cx_emu
    sizes = sorted({round(shape.size_pt * scale, 1) for shape in shapes if shape.size_pt})
    notes: list[str] = []
    if abs(scale - 1.0) > 0.01:
        notes.append(
            f"слайд {manifest.slide_size.cx_emu / 914400:.2f}″ — кегли приведены ×{scale:.2f}"
        )
    if not manifest.examples:
        notes.append("слайдов-примеров нет: дизайн-система только из макетов")
    return Measurement(
        name=name,
        masters=1 + len(manifest.extra_themes),
        layouts=len(manifest.layouts),
        examples=len(manifest.examples),
        layouts_with_examples=len({e.layout_id for e in manifest.examples if e.layout_id}),
        shapes=len(shapes),
        outside_placeholders=(len(outside) / len(shapes)) if shapes else 0.0,
        theme_fonts=sorted(
            {manifest.theme.fonts.major_latin, manifest.theme.fonts.minor_latin}
        ),
        used_fonts=[(f.family, f.chars) for f in manifest.usage.fonts if f.chars],
        palette=len(manifest.usage.palette),
        sizes_pt=sizes,
        seconds=round(seconds, 2),
        slide_scale=round(scale, 2),
        notes=notes,
    )


def _table(rows: list[Measurement]) -> str:
    head = (
        f"{'шаблон':34}{'мастеров':>9}{'макетов':>9}{'примеров':>10}"
        f"{'фигур':>7}{'вне ph':>8}{'палитра':>9}{'кеглей':>8}{'с':>7}"
    )
    lines = [head, "-" * len(head)]
    for row in rows:
        lines.append(
            f"{row.name[:33]:34}{row.masters:>9}{row.layouts:>9}{row.examples:>10}"
            f"{row.shapes:>7}{row.outside_placeholders:>7.0%}{row.palette:>9}"
            f"{len(row.sizes_pt):>8}{row.seconds:>7.2f}"
        )
        lines.append(f"    тема: {', '.join(row.theme_fonts) or '—'}")
        used = ", ".join(f"{family} {chars}" for family, chars in row.used_fonts[:4])
        lines.append(f"    набрано: {used or '—'}")
        for note in row.notes:
            lines.append(f"    ! {note}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="Шаблон .pptx/.potx или каталог с ними")
    parser.add_argument("--out", type=Path, default=None, help="Куда сложить JSON замера")
    args = parser.parse_args()

    targets = (
        sorted(p for p in args.target.iterdir() if p.suffix.lower() in {".pptx", ".potx"})
        if args.target.is_dir()
        else [args.target]
    )
    if not targets:
        print(f"в {args.target} нет ни одного шаблона", file=sys.stderr)
        return 1

    rows = [measure(path) for path in targets]
    print(_table(rows))
    if args.out:
        args.out.write_text(
            json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nзамер сохранён: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
