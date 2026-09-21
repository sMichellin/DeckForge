"""Кэш манифестов и предел времени на разметку макетов (D1).

Манифест, размеченный наспех, не должен становиться «готовым» для всех следующих прогонов,
а предразбор при деплое обязан заменять то, что уже лежит в кэше.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation

from deckforge.parsing.layout_kind import LayoutClassifier
from deckforge.parsing.template import TemplateParser

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


def _template(tmp_path: Path) -> Path:
    path = tmp_path / "default.pptx"
    Presentation().save(str(path))
    return path


def test_manifest_labelled_in_a_hurry_is_not_cached(tmp_path: Path) -> None:
    """Кончился предел — остаток макетов размечен эвристикой; в кэш такое не кладётся."""
    template = _template(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    classifier = LayoutClassifier()
    classifier.overdue = True

    TemplateParser(cache_dir=cache, classifier=classifier).parse(template)

    assert not list(cache.glob("*.json"))


def test_manifest_labelled_in_full_is_cached(tmp_path: Path) -> None:
    template = _template(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()

    TemplateParser(cache_dir=cache, classifier=LayoutClassifier()).parse(template)

    assert list(cache.glob("*.json"))


def test_warm_cache_replaces_what_is_already_cached(tmp_path: Path) -> None:
    """Предразбор разбирает заново, а не читает кэш: иначе старый манифест в нём остался бы."""
    import warm_template_cache

    template = _template(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    TemplateParser(cache_dir=cache, classifier=LayoutClassifier()).parse(template)
    (cached,) = cache.glob("*.json")
    cached.write_text(cached.read_text(encoding="utf-8").replace('"L00"', '"LXX"'), "utf-8")

    assert warm_template_cache.warm([template], cache, use_vlm=False) == 0

    assert '"LXX"' not in cached.read_text(encoding="utf-8")


def test_warm_cache_without_a_model_leaves_the_cache_alone(
    tmp_path: Path, monkeypatch: object
) -> None:
    """Модели нет — кэш не переписывается эвристикой (так и случилось на стенде 21.09)."""
    import warm_template_cache

    template = _template(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    TemplateParser(cache_dir=cache, classifier=LayoutClassifier()).parse(template)
    (cached,) = cache.glob("*.json")
    before = cached.read_text(encoding="utf-8")

    monkeypatch.setattr(warm_template_cache, "vlm_client", lambda: None)  # type: ignore[attr-defined]
    assert warm_template_cache.warm([template], cache, use_vlm=True) == 1

    assert cached.read_text(encoding="utf-8") == before


def test_warm_cache_asks_the_same_factory_as_the_run(monkeypatch: object) -> None:
    """Клиент — из фабрики реестра, а не из протокола (`VlmClient()` не создаётся)."""
    import warm_template_cache
    from deckforge.inference import factory

    sentinel = object()
    monkeypatch.setattr(factory, "vlm_judge", lambda role="vlm_judge": sentinel)  # type: ignore[attr-defined]
    assert warm_template_cache.vlm_client() is sentinel
