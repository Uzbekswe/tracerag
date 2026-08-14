from pathlib import Path

from tracerag.benchmark import render_markdown, write_report


def _report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "benchmark": "tracerag-v1.1",
        "corpus": {"name": "fastapi", "commit": "abc123"},
        "machine": {"os": "TestOS", "python": "3.13.0", "cpu_count": 8},
        "software": {"traceRAG_revision": "deadbeef", "ollama_tags": ["nomic-embed-text"]},
        "phases": [
            {
                "name": "clean_ingest",
                "processed_files": 3,
                "chunks": 12,
                "elapsed_ms": 1250.0,
                "embedding_calls": 1,
                "cache_hits": 0,
                "cache_misses": 12,
            },
            {
                "name": "unchanged_reingest",
                "processed_files": 0,
                "chunks": 0,
                "elapsed_ms": 40.0,
                "embedding_calls": 0,
                "cache_hits": 0,
                "cache_misses": 0,
            },
        ],
        "assertions": {"unchanged_embedding_calls": 0, "unchanged_under_10_seconds": True},
    }


def test_benchmark_markdown_contains_phase_and_environment_evidence() -> None:
    markdown = render_markdown(_report())

    assert "clean_ingest" in markdown
    assert "unchanged_reingest" in markdown
    assert "deadbeef" in markdown
    assert "nomic-embed-text" in markdown
    assert "zero embedding calls" in markdown


def test_write_report_writes_json_and_markdown(tmp_path: Path) -> None:
    paths = write_report(_report(), tmp_path, "fastapi")

    assert paths["json"] == tmp_path / "benchmark-fastapi.json"
    assert paths["markdown"] == tmp_path / "benchmark-fastapi.md"
    assert paths["json"].exists()
    assert paths["markdown"].exists()
