"""CLI DeckForge. Воспроизводимый запуск конфиг-файлом (C11).

    deckforge parse   template.pptx -o manifest.json
    deckforge ingest  content/ --brief brief.yaml -o content.json
    deckforge generate template.pptx content/ --variant A --config configs/default.yaml
    deckforge audit   deck.pptx --manifest manifest.json
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
    deck: Path = typer.Argument(..., exists=True),
    manifest: Path = typer.Option(..., "--manifest", exists=True),
    out: Path = typer.Option(Path("audit_report.json"), "--out", "-o"),
) -> None:
    """Прогон аудита по готовой колоде (change 15)."""
    raise NotImplementedError("change (15) audit-deterministic")


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
