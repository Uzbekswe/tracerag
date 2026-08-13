from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import Settings
from .corpus import fetch_fastapi
from .evaluation import compare_baseline, run_evaluation
from .ingest import Ingestor
from .ollama import OllamaClient, OllamaError, model_matches
from .service import RAGService

app = typer.Typer(help="TraceRAG: local-first, citation-first terminal RAG.")
corpus_app = typer.Typer(help="Fetch reproducible public demonstration corpora.")
app.add_typer(corpus_app, name="corpus")
console = Console()


def _service() -> RAGService:
    return RAGService(Settings())


@app.command()
def doctor() -> None:
    """Check runtime prerequisites without downloading or changing anything."""
    settings = Settings()
    rows = []
    rows.append(
        (
            "Python",
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            sys.version_info >= (3, 13),
        )
    )
    rows.append(
        (
            "Data directory",
            str(settings.data_dir),
            settings.data_dir.parent.exists() and os.access(settings.data_dir.parent, os.W_OK),
        )
    )
    client = OllamaClient(settings.ollama_url, settings.request_timeout)
    try:
        models = client.tags()
        rows.append(("Ollama", settings.ollama_url, True))
        rows.append(
            (
                f"Embedding model ({settings.embed_model})",
                "installed" if model_matches(models, settings.embed_model) else "missing",
                model_matches(models, settings.embed_model),
            )
        )
        rows.append(
            (
                f"Generation model ({settings.generation_model})",
                "installed" if model_matches(models, settings.generation_model) else "missing",
                model_matches(models, settings.generation_model),
            )
        )
    except (OllamaError, OSError, ValueError) as exc:
        rows.append(("Ollama", str(exc), False))
    docker_state = "not installed"
    if shutil.which("docker"):
        try:
            probe = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            docker_state = "daemon reachable" if probe.returncode == 0 else "daemon not running"
        except subprocess.TimeoutExpired:
            docker_state = "daemon probe timed out"
    rows.append(("Docker (optional)", docker_state, True))
    table = Table("Check", "Value", "Status")
    for name, value, passed in rows:
        table.add_row(name, value, "[green]OK[/green]" if passed else "[red]ACTION NEEDED[/red]")
    console.print(table)
    if any(not passed for _, _, passed in rows):
        raise typer.Exit(1)


@corpus_app.command("fetch")
def corpus_fetch(
    name: str = typer.Argument(..., help="Corpus name; currently only fastapi."),
) -> None:
    """Fetch a pinned public corpus."""
    if name != "fastapi":
        raise typer.BadParameter("Only the fastapi corpus is available in v1")
    settings = Settings()
    manifest = fetch_fastapi(settings.corpus_path / "fastapi")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"Fetched FastAPI corpus at commit [bold]{manifest['commit']}[/bold]")


@app.command()
def ingest(
    path: Path = typer.Argument(..., exists=True), collection: str | None = typer.Option(None)
) -> None:
    """Index Markdown and text-layer PDF files."""
    settings = Settings(collection=collection) if collection else Settings()
    service = RAGService(settings)
    corpus_sha = ""
    if settings.manifest_path.exists():
        corpus_sha = str(
            json.loads(settings.manifest_path.read_text(encoding="utf-8")).get("commit", "")
        )
    try:
        processed, chunks = Ingestor(
            settings, service.vectors, service.lexical, service.ollama
        ).ingest(path, corpus_sha)
    except (OllamaError, OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"Indexed [bold]{chunks}[/bold] chunks from [bold]{processed}[/bold] files.")


@app.command()
def documents(collection: str | None = typer.Option(None)) -> None:
    """List indexed source documents."""
    settings = Settings(collection=collection) if collection else Settings()
    table = Table("Source", "Chunks", "Status", "Content hash")
    for item in RAGService(settings).documents():
        table.add_row(
            str(item["source"]),
            str(item["chunks"]),
            str(item["status"]),
            str(item["content_hash"])[:12],
        )
    console.print(table)


@app.command()
def ask(
    question: str = typer.Argument(...),
    show_source: int | None = typer.Option(None),
    show_nearest: bool = typer.Option(False),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Ask a source-backed question."""
    try:
        result = _service().ask(question, show_nearest=show_nearest)
    except OllamaError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    if json_output:
        console.print_json(json.dumps(result.as_dict()))
        if result.refused:
            raise typer.Exit(2)
    elif result.refused:
        console.print(
            Panel(
                f"[yellow]I can't support an answer from the indexed documents.[/yellow]\n{result.refusal_reason}",
                title="TraceRAG refusal",
            )
        )
        if show_nearest:
            _print_sources(result.sources)
        raise typer.Exit(2)
    else:
        console.print(Panel(result.answer, title="TraceRAG answer"))
        _print_sources(result.sources, show_source)


def _print_sources(sources: list, show_source: int | None = None) -> None:
    table = Table("Citation", "Source", "Heading", "Score", "Preview")
    for index, hit in enumerate(sources, 1):
        if show_source == index:
            console.print(Panel(hit.chunk.text, title=f"[{index}] {hit.chunk.source}"))
        table.add_row(
            str(index),
            hit.chunk.source,
            hit.chunk.heading_path or "(root)",
            f"{hit.score:.3f}",
            hit.chunk.text[:300].replace("\n", " "),
        )
    if sources:
        console.print(table)


@app.command()
def eval(
    dataset: str = typer.Option("fastapi-v1", help="Dataset name or JSON path."),
    baseline: Path | None = typer.Option(None),
    limit: int | None = typer.Option(None, min=1, help="Evaluate only the first N records."),
) -> None:
    """Run the versioned evaluation dataset and write JSON/Markdown reports."""
    dataset_path = Path(dataset)
    if dataset == "fastapi-v1":
        dataset_path = Path("evals/dataset/fastapi-v1.json")
    try:
        report = run_evaluation(_service(), dataset_path, Path("reports"), limit=limit)
    except OllamaError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print_json(json.dumps(report["metrics"]))
    if baseline:
        regressions = compare_baseline(report, baseline)
        if regressions:
            for regression in regressions:
                console.print(f"[red]Regression:[/red] {regression}")
            raise typer.Exit(1)
    if not all(report["release_gate"].values()):
        raise typer.Exit(1)
