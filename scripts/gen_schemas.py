#!/usr/bin/env python3
"""Генерация JSON-схем из доменных моделей в `schemas/` и в `prompts/*/schema.json`.

Схемы — артефакт сборки, но коммитятся как golden-файлы: их расхождение с моделями
ловит `tests/golden/test_schemas.py` и означает несовместимое изменение контракта.

**Схема ответа модели — не то же самое, что схема контракта.** В `schemas/` уезжает полный
дамп доменной модели: слой обязан уметь принять всё, что в ней объявлено. В `prompts/`
уезжает суженная схема — то, что модели разрешено прислать. Разница в одном: открытую карту
(`dict[str, X]`) строгий режим провайдера выразить не может, потому что требует перечислить
в `required` все ключи объекта, а у карты они произвольны. Такое свойство из схемы ответа
выбрасывается — и по делу: карты в наших моделях заполняются кодом, а не моделью
(`SlideIR.fit_report` считает слой `layout`, `ChartBlock.axis_titles` берутся из `Dataset`).

Второе сужение объявляет сам промпт: `response_omit` в `meta.yaml` — поля, которые модель
заполнять **не должна**. Без него поле остаётся в схеме, а строгий режим делает его
обязательным: промпт композитора запрещал координаты, схема требовала `x, y, cx, cy`,
и модель клала минимум, который пускала схема, — точку 0, 0, 1, 1 (прогон f4cf4257e07f).

Третье сужение — виды блоков, которые контракт уже знает, а рендер ещё не рисует
(`WITHHELD_BLOCK_TYPES`). Контракт заводится раньше рендера, чтобы потоки не ждали друг
друга; но пока рисовать нечем, модель не должна мочь такой блок заказать — иначе слайд
теряет содержимое. Вид убирается из объединения блоков схемы ответа целиком: ветка
`oneOf`, запись `discriminator.mapping` и определения, на которые больше никто не ссылается.
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deckforge.config import PROMPTS_DIR, load_yaml

EXPORTED: dict[str, str] = {
    "template_manifest": "deckforge.domain.template.TemplateManifest",
    "content_package": "deckforge.domain.content.ContentPackage",
    "deck_plan": "deckforge.domain.plan.DeckPlan",
    "slide_ir": "deckforge.domain.slide.SlideIR",
    "deck_ir": "deckforge.domain.slide.DeckIR",
    "audit_report": "deckforge.domain.audit.AuditReport",
    "variant_profile": "deckforge.domain.variants.VariantProfile",
}


# Виды блоков, которые есть в контракте (`schemas/`), но которых нет в схемах ответа
# моделей (`prompts/*/schema.json`), — с причиной. Вид отсюда убирает тот change, который
# учит рендер его рисовать, вместе с новой версией промпта, где этот вид описан.
WITHHELD_BLOCK_TYPES: dict[str, str] = {
    "quote": "рендера цитаты ещё нет — compose-by-the-design-system (DG3)",
    "callout": "рендера callout ещё нет — compose-by-the-design-system (DG3)",
}


def resolve(dotted: str) -> type:
    module, _, name = dotted.rpartition(".")
    return getattr(import_module(module), name)  # type: ignore[no-any-return]


def dump(model: type) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"


def is_open_map(node: object) -> bool:
    """Свойство — карта с произвольными ключами, а не объект с фиксированным набором.

    Проверяется форма схемы, а не имя поля: невыразима в строгом режиме именно карта,
    и новое поле `dict[str, X]` обязано отсекаться само, без правки этого скрипта.
    """
    if not isinstance(node, dict):
        return False
    branches = node.get("anyOf") or node.get("oneOf") or [node]
    return any(
        isinstance(branch, dict)
        and "properties" not in branch
        and isinstance(branch.get("additionalProperties"), dict)
        for branch in branches
    )


def narrow(node: Any, dropped: set[str], omit: frozenset[str] = frozenset()) -> Any:
    """Убирает свойства-карты и поля из `omit` на любой глубине, включая `$defs`."""
    if isinstance(node, list):
        return [narrow(item, dropped, omit) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            kept = {}
            for name, sub in value.items():
                if is_open_map(sub) or name in omit:
                    dropped.add(name)
                    continue
                kept[name] = narrow(sub, dropped, omit)
            out[key] = kept
        else:
            out[key] = narrow(value, dropped, omit)

    # `required` чинится в том же узле, где выброшено свойство: строгий режим требует,
    # чтобы список и набор свойств совпадали, и осиротевшее имя отвергается наравне
    # с самой картой.
    if isinstance(out.get("properties"), dict) and isinstance(out.get("required"), list):
        out["required"] = [name for name in out["required"] if name in out["properties"]]
    return out


def _refs(node: Any) -> set[str]:
    """Имена `$defs`, на которые ссылается узел, на любой глубине."""
    if isinstance(node, list):
        return set().union(*(_refs(item) for item in node))
    if not isinstance(node, dict):
        return set()
    out = set().union(*(_refs(value) for value in node.values()))
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        out.add(ref.removeprefix("#/$defs/"))
    return out


def _reachable(schema: dict[str, Any]) -> set[str]:
    """Определения, достижимые от корня схемы по ссылкам."""
    defs = schema.get("$defs") or {}
    seen: set[str] = set()
    todo = _refs({key: value for key, value in schema.items() if key != "$defs"})
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        todo |= _refs(defs[name])
    return seen


def _without_variants(node: Any, withheld: frozenset[str], cut: set[str]) -> Any:
    """Убирает из дискриминированных объединений ветки с `type` из `withheld`."""
    if isinstance(node, list):
        return [_without_variants(item, withheld, cut) for item in node]
    if not isinstance(node, dict):
        return node

    out = {key: _without_variants(value, withheld, cut) for key, value in node.items()}
    discriminator = out.get("discriminator")
    if isinstance(discriminator, dict) and isinstance(discriminator.get("mapping"), dict):
        mapping = discriminator["mapping"]
        kinds = {kind for kind in withheld if kind in mapping}
        refs = {mapping[kind] for kind in kinds}
        if refs:
            cut.update(kinds)
            out["discriminator"] = {
                **discriminator,
                "mapping": {k: v for k, v in mapping.items() if v not in refs},
            }
            for key in ("oneOf", "anyOf"):
                if isinstance(out.get(key), list):
                    out[key] = [b for b in out[key] if not (
                        isinstance(b, dict) and b.get("$ref") in refs
                    )]
    return out


def withhold(schema: dict[str, Any], withheld: frozenset[str]) -> tuple[dict[str, Any], set[str]]:
    """Схема без видов блоков из `withheld` и без определений, осиротевших из-за этого.

    Второе значение — виды, которые действительно нашлись в схеме и убраны.

    Удаляются только те определения, которые были достижимы до сужения и перестали
    быть достижимы после: чужие сироты (например, `FitResult` после выброса карты
    `fit_report`) остаются как были, и схема ответа без таких видов не меняется ни на байт.
    """
    cut: set[str] = set()
    before = _reachable(schema)
    out = _without_variants(schema, withheld, cut)
    if not cut:
        return schema, cut
    orphaned = before - _reachable(out)
    out["$defs"] = {k: v for k, v in out["$defs"].items() if k not in orphaned}
    return out, cut


def response_schema(
    model: type,
    omit: frozenset[str] = frozenset(),
    withheld: frozenset[str] = frozenset(WITHHELD_BLOCK_TYPES),
) -> tuple[str, set[str]]:
    """Схема ответа модели: доменная минус невыразимое в строгом режиме, минус `omit`
    и минус виды блоков, которые рендер ещё не рисует (`withheld`)."""
    schema, cut = withhold(model.model_json_schema(), withheld)
    dropped = {f"блок {kind}" for kind in cut}
    schema = narrow(schema, dropped, omit)
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n", dropped


def main() -> int:
    out_dir = ROOT / "schemas"
    out_dir.mkdir(exist_ok=True)
    written = []
    for name, dotted in EXPORTED.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(dump(resolve(dotted)), encoding="utf-8")
        written.append(path.relative_to(ROOT).as_posix())

    # schema.json промптов, у которых объявлена response_model
    registry = load_yaml(PROMPTS_DIR / "registry.yaml").get("skills") or {}
    for skill, entry in registry.items():
        for version in sorted(p.name for p in (PROMPTS_DIR / skill).iterdir() if p.is_dir()):
            meta = load_yaml(PROMPTS_DIR / skill / version / "meta.yaml")
            dotted = meta.get("response_model")
            if not dotted:
                continue
            path = PROMPTS_DIR / skill / version / "schema.json"
            text, dropped = response_schema(
                resolve(dotted), frozenset(meta.get("response_omit") or ())
            )
            path.write_text(text, encoding="utf-8")
            note = f" (выброшено: {', '.join(sorted(dropped))})" if dropped else ""
            written.append(path.relative_to(ROOT).as_posix() + note)
        _ = entry

    for w in written:
        print(f"написано {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
