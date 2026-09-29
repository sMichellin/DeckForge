"""CLI DeckForge. Воспроизводимый запуск конфиг-файлом (C11).

    deckforge parse   template.pptx -o manifest.json
    deckforge design-system template.pptx -o дизайн-система.html
    deckforge ingest  content/ --brief brief.yaml -o content.json
    deckforge generate template.pptx content/ --variant A --config configs/default.yaml
    deckforge audit   <каталог прогона или фикстура> -o audit_report.json
    deckforge export  deck.json --format pptx,pdf,html
    deckforge checks  --list
"""

from __future__ import annotations

from pathlib import Path

import typer

from deckforge import __version__

app = typer.Typer(add_completion=False, help="Генератор презентаций в стиле произвольного шаблона")


@app.command()
def version() -> None:
    """Версия сервиса."""
    typer.echo(__version__)


@app.command()
def parse(
    template: Path = typer.Argument(..., exists=True, help="Файл .pptx или .potx"),
    out: Path = typer.Option(Path("manifest.json"), "--out", "-o"),
) -> None:
    """Шаблон → TemplateManifest (change 3)."""
    raise NotImplementedError("change (3) template-parsing-core")


@app.command(name="design-system")
def design_system(
    template: Path = typer.Argument(..., exists=True, help="Файл .pptx или .potx"),
    out: Path = typer.Option(
        None, "--out", "-o", help="Куда положить html; по умолчанию — рядом с шаблоном"
    ),
) -> None:
    """Шаблон → html-страница его дизайн-системы (change 30)."""
    from deckforge.designsystem import derive
    from deckforge.export.design_system_page import render
    from deckforge.parsing import TemplateParser
    from deckforge.parsing.package import NotATemplateError

    suffix = template.suffix.lower()
    if suffix not in {".pptx", ".potx"}:
        named = f"с расширением «{suffix}»" if suffix else "без расширения"
        typer.echo(
            f"Нужен шаблон презентации .pptx или .potx, "
            f"а файл «{template.name}» — {named}.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        # Без кэша: команду зовут ради свежего разбора конкретного файла, а не ради скорости.
        manifest = TemplateParser().parse(template, use_cache=False)
    except NotATemplateError as exc:
        # Сообщение уже написано для человека и начинается с имени файла — незачем
        # оборачивать его второй раз.
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        # Шаблон открылся, но разобрать нечего. Наружу идёт строка, а не трассировка.
        typer.echo(f"Шаблон «{template.name}» не разбирается: {exc}", err=True)
        raise typer.Exit(1) from exc

    default = template.with_name(f"{template.stem} — дизайн-система.html")
    target = default if out is None else out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(derive(manifest)), encoding="utf-8")
    typer.echo(str(target))


@app.command()
def ingest(
    content: Path = typer.Argument(..., exists=True),
    brief: Path = typer.Option(..., "--brief", exists=True),
    out: Path = typer.Option(Path("content.json"), "--out", "-o"),
) -> None:
    """Контент-пакет → ContentPackage (change 7)."""
    raise NotImplementedError("change (7) content-ingestion")


@app.command()
def generate(
    template: Path = typer.Argument(..., exists=True),
    content: Path = typer.Argument(..., exists=True),
    brief: Path = typer.Option(..., "--brief", exists=True),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c"),
    variant: str = typer.Option("A", "--variant", help="A, B, C или all"),
    out_dir: Path = typer.Option(Path("artifacts"), "--out-dir"),
    seed: int = typer.Option(-1, "--seed", help="По умолчанию — seed из конфига (C11)"),
    checkpoint: Path = typer.Option(
        None, "--checkpoint", help="Файл sqlite: прогон переживает перезапуск"
    ),
) -> None:
    """End-to-end: шаблон + контент → колода (change 17)."""
    import asyncio

    from deckforge.config import get_settings, load_run_config
    from deckforge.pipeline.run import (
        build_deps,
        collect_content_paths,
        generate_variant,
        load_brief,
        variants_for,
    )

    run = load_run_config(config_path=config)
    names = run.variants if variant.lower() == "all" else [variant]
    profiles = variants_for(names)
    paths = collect_content_paths(content)
    cache_dir = Path(get_settings().artifacts_dir) / "template-cache"

    for profile in profiles:
        target = out_dir / profile.variant_id
        deps = build_deps(
            load_brief(brief),
            run,
            target,
            cache_dir=cache_dir,
            asset_dir=target / "assets",
            profile=get_settings().profile,
        )
        result = asyncio.run(
            generate_variant(
                template,
                paths,
                profile,
                deps,
                seed=run.seed if seed < 0 else seed,
                checkpoint_path=checkpoint,
            )
        )
        report = result.report()
        result.write_report()
        typer.echo(
            f"вариант {profile.variant_id}: слайдов {report['slides']}, "
            f"{report['total_s']} с, форматы {', '.join(report['exports']) or '—'}"
        )
        for line in [*report["degradations"], *report["errors"]]:
            typer.echo(f"  ! {line}")


@app.command()
def audit(
    run: Path = typer.Argument(..., exists=True, file_okay=False),
    out: Path = typer.Option(Path("audit_report.json"), "--out", "-o"),
    variant: str = typer.Option("A", "--variant"),
) -> None:
    """Детерминированный аудит готового прогона — без модели и без стенда.

    `RUN` — каталог прогона стенда (`checkpoint.sqlite` рядом) или фикстура
    (`tests/fixtures/runs/…`). Change `the-deck-is-audited-offline`.
    """
    import asyncio
    import json

    from deckforge.pipeline.replay import load_snapshot, reaudit

    snapshot = load_snapshot(run, variant=variant)
    result = asyncio.run(reaudit(snapshot))
    payload = {
        "run_id": snapshot.run_id,
        "report": result.report.model_dump(mode="json"),
        "skipped_checks": result.skipped_checks,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = result.report.summary
    typer.echo(
        f"{snapshot.run_id}: ошибок {summary.errors}, предупреждений {summary.warnings}, "
        f"пропущено проверок {len(result.skipped_checks)} → {out}"
    )


@app.command()
def rebuild(
    run: Path = typer.Argument(..., exists=True, file_okay=False),
    out: Path = typer.Option(..., "--out", "-o", help="Каталог новой колоды"),
    variant: str = typer.Option("A", "--variant"),
) -> None:
    """Колода заново без модели: текст из чекпойнта прогона, вёрстка и аудит — текущим кодом.

    `RUN` — каталог прогона стенда (`checkpoint.sqlite`, `request.json`). Бриф и профиль
    прогона берутся из его запроса. Change `the-deck-is-rebuilt-without-a-model`.
    """
    import json
    import time

    from deckforge.config import get_settings, load_run_config
    from deckforge.domain.content import Brief
    from deckforge.layout.fonts import FontLibrary
    from deckforge.pipeline.deps import Deps
    from deckforge.pipeline.replay import rebuild as rebuild_run

    request_path = run / "request.json"
    request = (
        json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
    )
    profile = request.get("profile")
    deps = Deps(
        brief=Brief(
            purpose=str(request.get("purpose", "report")),
            audience=str(request.get("audience", "правление")),
            target_slides=request.get("target_slides", 12),
            language=str(request.get("language", "ru")),
        ),
        run=load_run_config(profile=str(profile) if profile else None),
        out_dir=out / "out",
        fonts=FontLibrary.default(),
        cache_dir=Path(get_settings().artifacts_dir) / "template-cache",
        asset_dir=out / "out" / "assets",
        work_dir=out / "out",
    )
    started = time.monotonic()
    result = rebuild_run(run, out, deps, variant=variant)
    audit = result.report().get("audit") or {}
    typer.echo(
        f"{result.run_id}: пересобрано без модели за {time.monotonic() - started:.0f} с, "
        f"ошибок аудита {audit.get('errors', '—')} → {out}"
    )


@app.command()
def export(
    deck: Path = typer.Argument(..., exists=True),
    formats: str = typer.Option("pptx,pdf,html", "--format", "-f"),
    out_dir: Path = typer.Option(Path("artifacts"), "--out-dir"),
) -> None:
    """Экспорт колоды в три формата (changes 16, 22)."""
    raise NotImplementedError("change (16) export-pptx-pdf")


@app.command()
def checks(list_: bool = typer.Option(False, "--list", "-l")) -> None:
    """Показать реестр проверок аудита."""
    from deckforge.audit import (
        REGISTRY,
        deterministic,  # noqa: F401  регистрация проверок
    )

    for item in REGISTRY.all():
        kind = "det " if item.deterministic else "vlm "
        typer.echo(f"{kind} {item.check_id:42} {item.severity.value:8} {item.title}")


if __name__ == "__main__":
    app()
