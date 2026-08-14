from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .corpus import get_profile, resolve_corpus_context
from .ingest import Ingestor, IngestSummary
from .service import RAGService


def _git_metadata() -> dict[str, object]:
    project_root = Path(__file__).resolve().parent.parent
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"revision": revision, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "dirty": None}


def _machine_metadata() -> dict[str, object]:
    return {
        "os": platform.platform(),
        "system": platform.system(),
        "arch": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
    }


def _phase(
    name: str,
    ingestor: Ingestor,
    path: Path,
    corpus_sha: str,
    embedding_calls: dict[str, int],
    *,
    rebuild: bool = False,
) -> dict[str, object]:
    before_calls = embedding_calls["count"]
    started = time.perf_counter()
    processed, chunks = ingestor.ingest(path, corpus_sha=corpus_sha, rebuild=rebuild)
    elapsed_ms = (time.perf_counter() - started) * 1000
    summary = ingestor.last_summary or IngestSummary()
    return {
        "name": name,
        "processed_files": processed,
        "chunks": chunks,
        "discovered": summary.discovered,
        "indexed": summary.indexed,
        "changed": summary.changed,
        "skipped": summary.skipped,
        "missing": summary.missing,
        "chunks_embedded": summary.chunks_embedded,
        "cache_hits": summary.cache_hits,
        "cache_misses": summary.cache_misses,
        "active_generation": summary.active_generation,
        "elapsed_ms": round(elapsed_ms, 2),
        "embedding_calls": embedding_calls["count"] - before_calls,
    }


def run_benchmark(settings: Settings, corpus_name: str, output_dir: Path) -> dict[str, object]:
    """Run isolated clean, unchanged, and one-file-edit ingest measurements."""

    profile = get_profile(corpus_name)
    source_root = settings.corpus_path / profile.name
    source = source_root / profile.allowed_path
    if not source.is_dir():
        raise ValueError(
            f"corpus allowlisted path is missing: {source}; run "
            f"tracerag corpus fetch {profile.name} first"
        )
    context = resolve_corpus_context(source)
    if context is None or context.provenance.name != profile.name:
        raise ValueError(
            f"corpus manifest is missing or invalid for {profile.name}; run "
            f"tracerag corpus fetch {profile.name} first"
        )
    manifest = context.manifest
    git = _git_metadata()
    file_count = manifest.get("file_count")
    if not isinstance(file_count, int):
        file_count = sum(1 for candidate in source.rglob("*") if candidate.is_file())

    with tempfile.TemporaryDirectory(prefix=f"tracerag-benchmark-{profile.name}-") as temporary:
        work_data = Path(temporary) / "data"
        work_source = work_data / "corpus" / profile.name / profile.allowed_path
        work_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, work_source)
        (work_data / "corpus" / profile.name / ".tracerag-corpus.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        work_settings = Settings(**{**settings.model_dump(), "data_dir": work_data})
        service = RAGService(work_settings)
        tags = service.ollama.tags()
        embedding_calls = {"count": 0}

        def new_ingestor() -> Ingestor:
            phase_service = RAGService(work_settings)
            original_embed = phase_service.ollama.embed

            def counted_embed(model: str, texts: list[str]) -> list[list[float]]:
                embedding_calls["count"] += 1
                return original_embed(model, texts)

            phase_service.ollama.embed = counted_embed  # type: ignore[method-assign]
            return Ingestor(
                work_settings,
                phase_service.vectors,
                phase_service.lexical,
                phase_service.ollama,
            )

        ingestor = new_ingestor()
        phases = [
            _phase(
                "clean_ingest",
                ingestor,
                work_source,
                profile.commit,
                embedding_calls,
                rebuild=True,
            ),
        ]
        ingestor = new_ingestor()
        phases.append(
            _phase(
                "unchanged_reingest",
                ingestor,
                work_source,
                profile.commit,
                embedding_calls,
            ),
        )
        edit_file = next(iter(sorted(work_source.rglob("*.md"))), None)
        if edit_file is None:
            raise ValueError(f"corpus has no Markdown files under {source}")
        edit_file.write_text(
            edit_file.read_text(encoding="utf-8")
            + "\n\n## TraceRAG benchmark edit\n\nThis paragraph measures incremental re-indexing.\n",
            encoding="utf-8",
        )
        ingestor = new_ingestor()
        phases.append(
            _phase(
                "one_file_edit_reingest",
                ingestor,
                work_source,
                profile.commit,
                embedding_calls,
            )
        )

    index_state = phases[-1].get("active_generation")
    report: dict[str, object] = {
        "schema_version": 1,
        "benchmark": "tracerag-v1.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": {
            "name": profile.name,
            "url": profile.url,
            "commit": profile.commit,
            "license": profile.license,
            "allowed_path": profile.allowed_path,
            "file_count": file_count,
        },
        "machine": _machine_metadata(),
        "software": {
            "traceRAG_revision": git["revision"],
            "traceRAG_dirty": git["dirty"],
            "python": sys.version.split()[0],
            "ollama_url": settings.ollama_url,
            "models": {
                "embedding": settings.embed_model,
                "generation": settings.generation_model,
            },
            "ollama_tags": tags,
        },
        "index": {
            "generation": index_state,
            "chunking_version": "structural-v1",
            "preprocessing_version": "parser-v1",
        },
        "phases": phases,
        "assertions": {
            "unchanged_embedding_calls": phases[1]["embedding_calls"],
            "unchanged_elapsed_seconds": round(float(phases[1]["elapsed_ms"]) / 1000, 3),
            "unchanged_target_seconds": 10.0,
            "unchanged_under_10_seconds": float(phases[1]["elapsed_ms"]) <= 10000,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_report(report, output_dir, profile.name)
    return report


def render_markdown(report: dict[str, object]) -> str:
    corpus = report.get("corpus", {})
    machine = report.get("machine", {})
    software = report.get("software", {})
    assertions = report.get("assertions", {})
    phases = report.get("phases", [])
    lines = [
        "# TraceRAG benchmark",
        "",
        f"Benchmark: `{report.get('benchmark', 'unknown')}`",
        f"Corpus: `{corpus.get('name', 'unknown')}` @ `{corpus.get('commit', 'unknown')}`",
        f"Allowed path: `{corpus.get('allowed_path', 'unknown')}`",
        "",
        "## Environment",
        "",
        f"- OS: `{machine.get('os', 'unknown')}`",
        f"- Architecture: `{machine.get('arch', 'unknown')}`",
        f"- CPUs: `{machine.get('cpu_count', 'unknown')}`",
        f"- Python: `{machine.get('python', software.get('python', 'unknown'))}`",
        f"- TraceRAG revision: `{software.get('traceRAG_revision', 'unknown')}`",
        f"- Ollama tags: `{', '.join(str(tag) for tag in software.get('ollama_tags', []))}`",
        "",
        "## Phases",
        "",
        "| Phase | Files | Chunks | Elapsed | Embedding calls | Cache hits | Cache misses |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for phase in phases:
        lines.append(
            f"| {phase['name']} | {phase['processed_files']} | {phase['chunks']} | "
            f"{float(phase['elapsed_ms']) / 1000:.2f}s | {phase['embedding_calls']} | "
            f"{phase['cache_hits']} | {phase['cache_misses']} |"
        )
    unchanged_ok = bool(assertions.get("unchanged_under_10_seconds"))
    unchanged_calls = assertions.get("unchanged_embedding_calls", "unknown")
    lines.extend(
        [
            "",
            "## No-change assertion",
            "",
            f"- Result: **{'PASS' if unchanged_ok and unchanged_calls == 0 else 'OBSERVED'}**",
            (
                f"- No-change elapsed: `{assertions.get('unchanged_elapsed_seconds', 'unknown')}s` "
                "(target: <= 10s on the M1 baseline)"
            ),
            f"- No-change embedding calls: `{unchanged_calls}` (target: zero embedding calls)",
            "",
            "The timing target is an environment-specific observation, not a universal guarantee.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, object], output_dir: Path, corpus_name: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"benchmark-{corpus_name}.json"
    markdown_path = output_dir / f"benchmark-{corpus_name}.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
