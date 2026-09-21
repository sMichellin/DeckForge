#!/usr/bin/env python3
"""Предразбор шаблонов в кэш манифестов. Задача D1.

Разметку макетов делает VLM через общий однослотовый сервер, и очередь к нему ничем
не ограничена: прогон `aa5eca9aa135` разбирал незнакомый шаблон 2375 с при бюджете
стадии 25 с (§12). В прогоне это лечится пределом времени с откатом на эвристику
(`DECKFORGE_LAYOUT_VLM_BUDGET_S`), но откат — размен качества на время.

Размен не нужен там, где спешить некуда. Шаблоны кейса известны заранее: этот скрипт
разбирает их **без предела** при деплое и кладёт манифесты в тот же кэш, из которого
их возьмёт прогон. Дальше разбор известного шаблона стоит чтения json.

    python scripts/warm_template_cache.py tests/fixtures/templates/*.pptx

Кэш инвалидируется сменой `PARSER_VERSION`: после правки парсера скрипт надо прогнать
заново, иначе прогон честно посчитает кэш устаревшим и разберёт шаблон сам.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.config import get_settings
from deckforge.parsing.layout_kind import LayoutClassifier
from deckforge.parsing.template import PARSER_VERSION, TemplateParser


def vlm_client() -> object | None:
    """Клиент VLM — тот же, что получает прогон (`pipeline/run.py`, `layout_vlm`).

    Прежде здесь создавался `VlmClient()`, а это протокол: экземпляра у него нет, и скрипт
    на стенде за секунду переписал кэш всех четырёх шаблонов разметкой одной эвристикой,
    сообщив «VLM недоступен». `None` — модели в реестре нет вовсе.
    """
    from deckforge.inference.factory import vlm_judge

    try:
        return vlm_judge("vlm_judge")
    except (KeyError, ValueError) as error:
        print(f"VLM не объявлен в реестре моделей ({error})")
        return None


def warm(paths: list[Path], cache_dir: Path, use_vlm: bool = True) -> int:
    parser_args = {"cache_dir": cache_dir}
    failed = 0
    for path in paths:
        if not path.is_file():
            print(f"{path}: файла нет — пропущен")
            failed += 1
            continue
        vlm = vlm_client() if use_vlm else None
        if use_vlm and vlm is None:
            # Кэш без модели хуже, чем никакого: прогон взял бы его как готовый и не позвал
            # модель даже при свободном сервере. Эвристика в кэш — только по `--no-vlm`.
            print(f"{path.name}: модели нет — кэш не тронут (эвристикой: --no-vlm)")
            failed += 1
            continue
        # Свой классификатор на каждый шаблон: предел времени у него нет, а счётчики
        # отказов должны относиться к одному шаблону, а не копиться на все.
        classifier = LayoutClassifier(vlm=vlm, budget_s=None)
        started = time.monotonic()
        try:
            # Разбирать заново, а не читать кэш: в нём может лежать манифест, снятый
            # с другой моделью или без неё, — предразбор затем и нужен, чтобы его заменить.
            parser = TemplateParser(classifier=classifier, **parser_args)  # type: ignore[arg-type]
            manifest = parser.parse(path, use_cache=False)
            parser.save_cached(manifest)
        except Exception as error:
            print(f"{path.name}: разобрать не удалось — {error}")
            failed += 1
            continue
        spent = time.monotonic() - started
        by_vlm = sum(1 for layout in manifest.layouts if "vlm" in layout.kind_source)
        print(
            f"{path.name}: макетов {len(manifest.layouts)}, из них моделью {by_vlm}; "
            f"{spent:.0f} с; вызовов {classifier.calls}"
            + (f"; отказы {dict(classifier.failures)}" if classifier.failures else "")
        )
    return failed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("templates", nargs="+", type=Path)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="куда класть манифесты; по умолчанию тот же кэш, что берёт прогон",
    )
    parser.add_argument(
        "--no-vlm", action="store_true", help="размечать только эвристикой, без модели"
    )
    args = parser.parse_args(argv)

    cache_dir = args.cache_dir or Path(get_settings().artifacts_dir) / "template-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"кэш: {cache_dir}, версия парсера {PARSER_VERSION}")

    failed = warm(list(args.templates), cache_dir, use_vlm=not args.no_vlm)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
