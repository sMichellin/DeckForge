#!/usr/bin/env python3
"""Замер классификации макетов: эвристика против эвристики с VLM. Change (5).

Зачем отдельный скрипт, а не разовая проба: вопрос «стало ли лучше» возникает при каждой
правке эвристики, промпта или превью. Замер, который нельзя повторить одной командой,
через неделю никто не повторит.

    DECKFORGE_MODELS_CONFIG=models.ovh.yaml \
    DECKFORGE_VLM_BASE_URL=... DECKFORGE_VLM_API_KEY=... \
    python scripts/bench_layout_classification.py tests/fixtures/templates --preview both

Эталон — **названия макетов**. Классификатор их не видит вовсе, поэтому сигнал
независимый. Но эталон грубый: в VK Tech полтора десятка разных макетов называются
«Титульный слайд», и там метрика даёт ноль при любой логике. Числа годятся для сравнения
вариантов между собой, гейтом «≥ 80 %» они быть не могут — для него нужна ручная разметка.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.domain.template import TemplateManifest
from deckforge.parsing import TemplateParser
from deckforge.parsing.layout_kind import (
    LayoutClassifier,
    classify_heuristic,
    geometry_signature,
    needs_vlm,
)

#: Название макета → допустимые виды. Несколько вариантов там, где название не различает:
#: «фото» может быть и полноэкранной картинкой, и колонкой рядом с текстом.
EXPECTED_BY_NAME: list[tuple[str, set[str]]] = [
    (r"титул|title|обложка", {"title"}),
    (r"спасибо|thank|контакт|прощал", {"closing"}),
    (r"содержан|оглавлен|agenda|повестк", {"bullets", "section"}),
    (r"раздел|section|глава", {"section"}),
    (r"цитат|quote", {"quote"}),
    (r"таблиц|table", {"table"}),
    (r"график|диаграмм|chart", {"chart"}),
    (r"фактоид|кпэ|kpi|цифр|метрик|статистик", {"kpi", "two_column"}),
    (r"две колонк|2 колонк|two.?column", {"two_column"}),
    (r"фото|скриншот|изображен|картинк|image|паттерн", {"image_full", "two_column"}),
    (r"пункт|список|буллет|bullet|текст", {"bullets"}),
]


def expected(name: str) -> set[str] | None:
    low = name.lower()
    for pattern, kinds in EXPECTED_BY_NAME:
        if re.search(pattern, low):
            return kinds
    return None


def uncertain_representatives(manifest: TemplateManifest) -> list[str]:
    """Спорные макеты, по одному на геометрию: одинаковые спрашиваются один раз."""
    seen: set[str] = set()
    out: list[str] = []
    for layout in manifest.layouts:
        if not needs_vlm(layout.kind_confidence):
            continue
        signature = geometry_signature(layout.placeholders, manifest.slide_size)
        if signature not in seen:
            seen.add(signature)
            out.append(layout.layout_id)
    return out


def score(manifest: TemplateManifest, kinds: dict[str, str]) -> tuple[int, int]:
    ok = total = 0
    for layout in manifest.layouts:
        wanted = expected(layout.name)
        if wanted is None:
            continue
        total += 1
        ok += kinds[layout.layout_id] in wanted
    return ok, total


def run(paths: list[Path], preview_mode: str, votes: int) -> int:
    from deckforge.inference import client_for
    from deckforge.inference.vlm import VlmJudge

    judge = None
    if preview_mode != "none":
        judge = VlmJudge(client_for("vlm_judge"), skill_ref="layout_classifier@1.0.0")

    grand: dict[str, list[int]] = {"heuristic": [0, 0], "schematic": [0, 0], "composite": [0, 0]}

    for path in paths:
        manifest = TemplateParser().parse(path, use_cache=False)
        base = {
            layout.layout_id: classify_heuristic(
                layout.placeholders, manifest.slide_size, layout.shapes
            )[0].value
            for layout in manifest.layouts
        }
        ok, total = score(manifest, base)
        grand["heuristic"][0] += ok
        grand["heuristic"][1] += total
        print(f"\n{path.name}: макетов {len(manifest.layouts)}, сверяемых {total}")
        print(f"  эвристика                {ok}/{total}" + (f" = {ok/total:.0%}" if total else ""))

        if judge is None:
            continue

        wanted = uncertain_representatives(manifest)
        for mode in ("schematic", "composite"):
            if preview_mode not in (mode, "both"):
                continue
            with tempfile.TemporaryDirectory() as tmp:
                provider = _provider(mode, path, manifest, Path(tmp), wanted)
                if provider is None:
                    print(f"  {mode:24} пропущен: LibreOffice недоступен")
                    continue
                classifier = LayoutClassifier(vlm=judge, preview=provider, votes=votes)
                start = time.time()
                live = TemplateParser(classifier=classifier).parse(path, use_cache=False)
                elapsed = time.time() - start

            kinds = {layout.layout_id: layout.kind.value for layout in live.layouts}
            ok, total = score(live, kinds)
            grand[mode][0] += ok
            grand[mode][1] += total
            fails = dict(classifier.failures)
            print(
                f"  + VLM, превью {mode:10} {ok}/{total}"
                + (f" = {ok/total:.0%}" if total else "")
                + f"  вызовов {classifier.calls}, {elapsed:.0f} с"
                + (f", отказы {fails}" if fails else "")
            )

    print("\nИТОГО")
    for mode, (ok, total) in grand.items():
        if total:
            print(f"  {mode:24} {ok}/{total} = {ok/total:.0%}")
    return 0


def _provider(
    mode: str, template: Path, manifest: TemplateManifest, tmp: Path, wanted: list[str]
) -> object | None:
    from deckforge.parsing.layout_preview import SchematicPreview

    if mode == "schematic":
        return SchematicPreview()

    from deckforge.rendering.layout_preview import CompositePreview
    from deckforge.rendering.soffice import SofficeRenderer

    if not SofficeRenderer().available:
        return None
    return CompositePreview(template, manifest, tmp, only=wanted)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("templates", type=Path, help="каталог с .pptx или один файл")
    parser.add_argument(
        "--preview",
        choices=["none", "schematic", "composite", "both"],
        default="schematic",
        help="какое превью давать модели; none — только эвристика, без вызовов",
    )
    parser.add_argument("--votes", type=int, default=3)
    args = parser.parse_args()

    root = args.templates
    paths = sorted(root.rglob("*.pptx")) if root.is_dir() else [root]
    if not paths:
        print(f"в {root} нет .pptx", file=sys.stderr)
        return 1
    return run(paths, args.preview, args.votes)


if __name__ == "__main__":
    raise SystemExit(main())
