import json
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

import tracerag.cli as cli_module
from tracerag.config import Settings
from tracerag.corpus import CLIPPY_COMMIT
from tracerag.ingest import IngestSummary

runner = CliRunner()


class _DocumentsService:
    def __init__(self, _settings) -> None:
        pass

    def documents(self) -> list[dict[str, object]]:
        return [
            {
                "source": "/tmp/guide.md",
                "chunks": 3,
                "status": "current",
                "content_hash": "abcdef1234567890",
            },
            {
                "source": "/tmp/changed.md",
                "chunks": 2,
                "status": "changed",
                "content_hash": "1234567890abcdef",
            },
            {
                "source": "/tmp/missing.md",
                "chunks": 1,
                "status": "missing",
                "content_hash": "fedcba0987654321",
            },
        ]


def test_documents_default_is_a_bounded_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "RAGService", _DocumentsService)
    monkeypatch.setattr(cli_module, "Settings", lambda **_: Settings(data_dir=tmp_path))

    result = runner.invoke(cli_module.app, ["documents"])

    assert result.exit_code == 0
    assert "Sources" in result.output
    assert "Chunks" in result.output
    assert "Current" in result.output
    assert "Changed" in result.output
    assert "Missing" in result.output
    assert "/tmp/guide.md" not in result.output


def test_documents_verbose_retains_source_diagnosis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "RAGService", _DocumentsService)
    monkeypatch.setattr(cli_module, "Settings", lambda **_: Settings(data_dir=tmp_path))

    result = runner.invoke(cli_module.app, ["documents", "--verbose"])

    assert result.exit_code == 0
    assert "/tmp/guide.md" in result.output
    assert "current" in result.output
    assert "Content hash" in result.output


def test_ingest_reporter_prints_aggregate_summary() -> None:
    output = Console(record=True, width=120)
    reporter = cli_module.RichIngestReporter(output)
    reporter.start()
    reporter("discovery", {"discovered": 10})
    reporter("planning", {"changed": 2, "skipped": 8, "missing": 0})
    reporter("cache", {"cache_hits": 3, "cache_misses": 4})
    reporter.finish(
        IngestSummary(
            discovered=10,
            indexed=2,
            indexed_with_chunks=2,
            changed=2,
            skipped=8,
            chunks_embedded=4,
            cache_hits=3,
            cache_misses=4,
            active_generation="generation-123",
            elapsed_ms=1250,
        )
    )

    text = output.export_text()
    assert "Ingest summary" in text
    assert "index updated" in text
    assert "Cache hits" in text
    assert "Indexed with chunks" in text
    assert "generation-123" in text
    assert "1.25s" in text


def test_ingest_reporter_labels_no_change_runs() -> None:
    output = Console(record=True, width=120)
    reporter = cli_module.RichIngestReporter(output)
    reporter.start()
    reporter.finish(IngestSummary(discovered=10, skipped=10, active_generation="generation-123"))

    assert "no changes" in output.export_text()


def test_ingest_reporter_labels_empty_sources() -> None:
    output = Console(record=True, width=120)
    reporter = cli_module.RichIngestReporter(output)
    reporter.start()
    reporter.finish(IngestSummary(discovered=2, indexed=2, indexed_with_chunks=1, empty=1))

    text = output.export_text()
    assert "Indexed with chunks" in text
    assert "Empty parsed" in text


def test_ingest_yes_without_prune_has_usage_error(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir()

    result = runner.invoke(cli_module.app, ["ingest", str(source), "--yes"])

    assert result.exit_code == 2
    assert "--yes requires --prune" in result.output


def test_corpus_fetch_clippy_prints_pinned_commit_and_allowlist(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(data_dir=tmp_path)
    captured: dict[str, Path] = {}

    def fake_fetch(destination: Path) -> dict[str, object]:
        captured["destination"] = destination
        return {
            "name": "clippy",
            "url": "https://github.com/rust-lang/rust-clippy.git",
            "commit": CLIPPY_COMMIT,
            "license": "MIT OR Apache-2.0",
            "allowed_path": "book/src/development",
            "file_count": 24,
        }

    monkeypatch.setattr(cli_module, "Settings", lambda **_: settings)
    monkeypatch.setattr(cli_module, "fetch_clippy", fake_fetch)

    result = runner.invoke(cli_module.app, ["corpus", "fetch", "clippy"])

    assert result.exit_code == 0
    assert CLIPPY_COMMIT in result.output
    assert "book/src/development" in result.output
    assert captured["destination"] == tmp_path / "corpus" / "clippy"
    assert not settings.manifest_path.exists()


def test_eval_rejects_malformed_dataset_with_nonzero_exit(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = tmp_path / "bad.json"
    dataset.write_text(
        json.dumps(
            {
                "dataset": "bad",
                "version": "1.1.0",
                "records": [{"id": "bad", "question": "?", "in_scope": True}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_service", lambda: object())

    result = runner.invoke(cli_module.app, ["eval", "--dataset", str(dataset)])

    assert result.exit_code == 1
    assert "evidence_targets" in result.output


def test_benchmark_help_exposes_fastapi_profile() -> None:
    result = runner.invoke(cli_module.app, ["benchmark", "--help"])

    assert result.exit_code == 0
    assert "--corpus" in result.output
    assert "fastapi" in result.output


def test_eval_resolves_clippy_dataset_profile(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Path] = {}

    def fake_evaluation(_service, dataset_path: Path, _output_dir: Path, limit=None):
        captured["dataset"] = dataset_path
        return {"metrics": {"citation_validity": 1.0}, "release_gate": {"ok": True}}

    monkeypatch.setattr(cli_module, "run_evaluation", fake_evaluation)
    monkeypatch.setattr(cli_module, "_service", lambda: object())

    result = runner.invoke(cli_module.app, ["eval", "--dataset", "clippy-v1"])

    assert result.exit_code == 0
    assert captured["dataset"] == Path("evals/dataset/clippy-v1.json")
