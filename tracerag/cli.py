from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .benchmark import run_benchmark
from .cache import EmbeddingCache
from .config import Settings
from .corpus import CORPUS_PROFILES, fetch_clippy, fetch_fastapi, resolve_corpus_context
from .errors import IndexCompatibilityError, PruneConfirmationRequired
from .evaluation import DatasetValidationError, compare_baseline, run_evaluation
from .index_state import IndexStateStore
from .ingest import Ingestor, IngestSummary
from .ollama import OllamaClient, OllamaError, model_matches
from .service import RAGService

app = typer.Typer(help="TraceRAG: local-first, citation-first terminal RAG.")
corpus_app = typer.Typer(help="Fetch reproducible public demonstration corpora.")
cache_app = typer.Typer(help="Inspect or clear the local embedding cache.")
app.add_typer(corpus_app, name="corpus")
app.add_typer(cache_app, name="cache")
console = Console()


class RichIngestReporter:
    """Render bounded aggregate ingest progress without coupling presentation to ingest."""

    _stages: ClassVar[tuple[str, ...]] = (
        "discovery",
        "planning",
        "parsing",
        "cache",
        "embedding",
        "staging",
        "activation",
        "cleanup",
    )
    _labels: ClassVar[dict[str, str]] = {
        "discovery": "Discovering files",
        "planning": "Planning changes",
        "parsing": "Parsing and chunking",
        "cache": "Reusing embedding cache",
        "embedding": "Embedding batches",
        "staging": "Staging index",
        "activation": "Activating index",
        "cleanup": "Cleaning up old index",
    }

    def __init__(self, output: Console | None = None) -> None:
        self.output = output or console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=self.output,
            transient=True,
        )
        self._task_id: int | None = None
        self._seen_stages: set[str] = set()

    def start(self) -> None:
        if self._task_id is not None:
            return
        self._task_id = self.progress.add_task("Preparing ingest", total=len(self._stages))
        self.progress.start()

    def __call__(self, stage: str, details: dict[str, object]) -> None:
        if stage in {"complete", "embedding_batch"}:
            return
        if self._task_id is None:
            self.start()
        if self._task_id is None:  # pragma: no cover - guarded by start
            return
        if stage in self._stages and stage not in self._seen_stages:
            self._seen_stages.add(stage)
            self.progress.advance(self._task_id)
        description = self._description(stage, details)
        if description:
            self.progress.update(self._task_id, description=description)

    def finish(self, summary: IngestSummary) -> None:
        if self._task_id is not None:
            self.progress.update(
                self._task_id,
                completed=len(self._seen_stages),
                description="Ingest complete",
            )
            self.progress.stop()
            self._task_id = None
        self.output.print(self._summary_table(summary))

    def stop(self) -> None:
        if self._task_id is not None:
            self.progress.stop()
            self._task_id = None

    @staticmethod
    def _description(stage: str, details: dict[str, object]) -> str:
        label = RichIngestReporter._labels.get(stage, stage.title())
        if stage == "discovery":
            return f"{label} • {details.get('discovered', 0)} files"
        if stage == "planning":
            return (
                f"{label} • changed={details.get('changed', 0)} "
                f"skipped={details.get('skipped', 0)} "
                f"missing={details.get('missing', 0)}"
            )
        if stage == "parsing":
            return f"{label} • {details.get('files', 0)} files"
        if stage == "cache":
            return (
                f"{label} • hits={details.get('cache_hits', 0)} "
                f"misses={details.get('cache_misses', 0)}"
            )
        if stage == "embedding":
            return (
                f"{label} • {details.get('chunks', 0)} chunks, "
                f"{details.get('batches', 0)} batches"
            )
        return label

    @staticmethod
    def _summary_table(summary: IngestSummary) -> Table:
        result = "no changes" if summary.indexed == 0 and summary.pruned == 0 else "index updated"
        table = Table("Ingest summary", "Value")
        rows = (
            ("Result", result),
            ("Discovered", summary.discovered),
            ("Indexed", summary.indexed),
            ("Indexed with chunks", summary.indexed_with_chunks),
            ("Empty parsed", summary.empty),
            ("Changed", summary.changed),
            ("Skipped", summary.skipped),
            ("Missing", summary.missing),
            ("Pruned", summary.pruned),
            ("Unsupported", summary.unsupported),
            ("Chunks embedded", summary.chunks_embedded),
            ("Cache hits", summary.cache_hits),
            ("Cache misses", summary.cache_misses),
            ("Active index version", summary.active_generation or "(none)"),
            ("Elapsed", f"{summary.elapsed_ms / 1000:.2f}s"),
        )
        for name, value in rows:
            table.add_row(name, str(value))
        return table


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
    rows.append(("Corpus profiles", ", ".join(CORPUS_PROFILES), True))
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
    name: str = typer.Argument(..., help="Corpus profile: fastapi or clippy."),
) -> None:
    """Fetch a pinned public corpus."""
    try:
        profile = CORPUS_PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(CORPUS_PROFILES))
        raise typer.BadParameter(f"Unknown corpus profile; choose from {choices}") from exc
    settings = Settings()
    destination = settings.corpus_path / profile.name
    fetcher = fetch_fastapi if name == "fastapi" else fetch_clippy
    try:
        manifest = fetcher(destination)
    except (OllamaError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(
        f"Fetched {profile.display_name} corpus at commit [bold]{manifest['commit']}[/bold]"
    )
    console.print(f"Allowed ingest path: {destination / profile.allowed_path}")


@app.command()
def ingest(
    path: Path = typer.Argument(..., exists=True),
    collection: str | None = typer.Option(None),
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        help="Explicitly replace an incompatible or legacy index before ingesting.",
    ),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Plan removal of indexed sources that are missing from PATH.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Confirm deletion when used with --prune.",
    ),
) -> None:
    """Index Markdown and text-layer PDF files."""
    if yes and not prune:
        raise typer.BadParameter("--yes requires --prune")
    settings = Settings(collection=collection) if collection else Settings()
    service = RAGService(settings)
    corpus_context = resolve_corpus_context(path)
    corpus_sha = corpus_context.provenance.commit if corpus_context else ""
    ingestor = Ingestor(settings, service.vectors, service.lexical, service.ollama)
    reporter = RichIngestReporter()
    reporter.start()
    try:
        processed, chunks = ingestor.ingest(
            path,
            corpus_sha,
            rebuild=rebuild,
            prune=prune,
            prune_confirmed=yes,
            reporter=reporter,
            corpus_provenance=corpus_context.provenance if corpus_context else None,
        )
    except (IndexCompatibilityError, OllamaError, OSError, ValueError) as exc:
        reporter.stop()
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except PruneConfirmationRequired as exc:
        reporter.stop()
        console.print(f"[yellow]Prune preview:[/yellow]\n{exc}")
        raise typer.Exit(2) from exc
    if ingestor.last_summary is not None:
        reporter.finish(ingestor.last_summary)
    else:  # pragma: no cover - ingest always records a summary on success
        reporter.stop()
    console.print(f"Indexed [bold]{chunks}[/bold] chunks from [bold]{processed}[/bold] files.")


@app.command()
def documents(
    collection: str | None = typer.Option(None),
    verbose: bool = typer.Option(False, "--verbose", help="Show one diagnostic row per source."),
) -> None:
    """List indexed source documents."""
    settings = Settings(collection=collection) if collection else Settings()
    try:
        items = RAGService(settings).documents()
        if verbose:
            table = Table("Source", "Chunks", "Status", "Content hash")
            for item in items:
                table.add_row(
                    str(item["source"]),
                    str(item["chunks"]),
                    str(item["status"]),
                    str(item["content_hash"])[:12],
                )
            console.print(table)
            return
        identity = IndexStateStore(settings.index_state_path).load()
    except IndexCompatibilityError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    current = sum(item["status"] == "current" for item in items)
    changed = sum(item["status"] == "changed" for item in items)
    missing = sum(item["status"] == "missing" for item in items)
    empty = sum(item["status"] == "empty" for item in items)
    indexed_with_chunks = sum(int(item["chunks"]) > 0 for item in items)
    chunks = sum(int(item["chunks"]) for item in items)
    summary = Table("Documents", "Value")
    summary.add_row("Sources", str(len(items)))
    summary.add_row("Chunks", str(chunks))
    summary.add_row("Indexed with chunks", str(indexed_with_chunks))
    summary.add_row("Empty parsed", str(empty))
    summary.add_row("Current", str(current))
    summary.add_row("Changed", str(changed))
    summary.add_row("Missing", str(missing))
    summary.add_row("Active generation", identity.generation if identity else "(none)")
    if identity:
        format_version = (
            f"schema={identity.schema_version}, "
            f"chunking={identity.chunking_version}, "
            f"preprocessing={identity.preprocessing_version}"
        )
    else:
        format_version = "unversioned"
    summary.add_row("Index format", format_version)
    console.print(summary)


@cache_app.command("status")
def cache_status() -> None:
    """Show the local embedding cache size and entry count."""
    settings = Settings()
    status = EmbeddingCache(
        settings.embedding_cache_path, settings.embedding_cache_max_bytes
    ).status()
    table = Table("Cache", "Entries", "Bytes", "Limit")
    table.add_row(
        str(settings.embedding_cache_path),
        str(status.entries),
        str(status.bytes),
        str(status.max_bytes),
    )
    console.print(table)


@cache_app.command("clear")
def cache_clear(
    yes: bool = typer.Option(False, "--yes", help="Confirm deleting cached embeddings."),
) -> None:
    """Delete cached embeddings without touching indexed documents."""
    if not yes:
        raise typer.BadParameter("--yes is required to clear the embedding cache")
    settings = Settings()
    removed = EmbeddingCache(
        settings.embedding_cache_path, settings.embedding_cache_max_bytes
    ).clear()
    console.print(f"Cleared [bold]{removed}[/bold] cached embedding entries.")


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
    output_dir: Path = typer.Option(
        Path("reports"), "--output-dir", help="Directory for dataset-specific reports."
    ),
) -> None:
    """Run the versioned evaluation dataset and write JSON/Markdown reports."""
    dataset_path = Path(dataset)
    if dataset in {"fastapi-v1", "clippy-v1"}:
        dataset_path = Path(f"evals/dataset/{dataset}.json")
    try:
        report = run_evaluation(_service(), dataset_path, output_dir, limit=limit)
    except (DatasetValidationError, OllamaError) as exc:
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


@app.command()
def benchmark(
    corpus: str = typer.Option("fastapi", "--corpus", help="Corpus profile to benchmark."),
    output_dir: Path = typer.Option(
        Path("reports"), "--output-dir", help="Directory for benchmark JSON and Markdown."
    ),
) -> None:
    """Measure clean, unchanged, and one-file-edit ingestion phases."""
    try:
        report = run_benchmark(Settings(), corpus, output_dir)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    paths = {
        "json": output_dir / f"benchmark-{corpus}.json",
        "markdown": output_dir / f"benchmark-{corpus}.md",
    }
    assertions = report.get("assertions", {})
    console.print(
        f"Benchmark complete: unchanged ingest {assertions.get('unchanged_elapsed_seconds', '?')}s, "
        f"{assertions.get('unchanged_embedding_calls', '?')} embedding calls"
    )
    console.print(f"JSON: {paths['json']}\nMarkdown: {paths['markdown']}")
