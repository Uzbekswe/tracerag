import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tracerag.evaluation import (
    DatasetValidationError,
    compare_baseline,
    match_evidence_targets,
    run_evaluation,
    validate_dataset,
)
from tracerag.index_state import CorpusProvenance, IndexStateStore
from tracerag.models import AnswerResult, Chunk, SearchHit


class FakeSettings:
    generation_model = "qwen3:4b"
    embed_model = "nomic-embed-text"
    min_retrieval_score = 0.72
    model_context = 4096
    manifest_path = Path("/does/not/exist")


class FakeService:
    settings = FakeSettings()

    def retrieve(self, _question: str, top_k: int = 5) -> list[SearchHit]:
        return [
            SearchHit(
                Chunk("id", "FastAPI is a web framework.", "/docs/guide.md", 0, "Intro", "hash"),
                0.9,
                dense_score=0.9,
            )
        ]

    def ask(self, question: str, hits: list[SearchHit]) -> AnswerResult:
        if "outside" in question:
            return AnswerResult(question, "", [], True, "unsupported")
        return AnswerResult(question, "FastAPI is a web framework [1].", hits)


def test_evaluation_writes_report_and_handles_refusal(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            {
                "dataset": "test",
                "version": "1.1.0",
                "records": [
                    {
                        "id": "in",
                        "question": "What is FastAPI?",
                        "in_scope": True,
                        "evidence_targets": [{"source": "docs/guide.md", "heading": "Intro"}],
                        "expected_facts": ["web framework"],
                    },
                    {
                        "id": "out",
                        "question": "What is outside?",
                        "in_scope": False,
                        "evidence_targets": [],
                        "expected_facts": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_evaluation(FakeService(), dataset, tmp_path / "reports")

    assert report["metrics"] == {
        "citation_validity": 1.0,
        "recall_at_5": 1.0,
        "factuality": 1.0,
    }
    assert (tmp_path / "reports/test.json").exists()
    assert (tmp_path / "reports/test.md").exists()
    assert report["cases"][0]["matched_target"] == {
        "source": "docs/guide.md",
        "heading": "intro",
        "rank": 1,
    }
    assert report["cases"][0]["sources"][0]["source"] == "guide.md"
    assert report["cases"][1]["matched_target"] is None
    assert "Matched target" in (tmp_path / "reports/test.md").read_text(encoding="utf-8")


def _active_profile_settings(tmp_path: Path, name: str, commit: str) -> SimpleNamespace:
    data_dir = tmp_path / "data"
    settings = SimpleNamespace(
        generation_model="qwen3:4b",
        embed_model="nomic-embed-text",
        min_retrieval_score=0.72,
        model_context=4096,
        corpus_path=data_dir / "corpus",
        index_state_path=data_dir / "index-state.json",
        embedding_cache_path=data_dir / "embedding-cache",
        embedding_cache_max_bytes=512,
    )
    settings.corpus_path.joinpath(name, "docs").mkdir(parents=True)
    identity = IndexStateStore.new(
        collection="tracerag",
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        embedding_dimension=2,
        corpus_provenance=CorpusProvenance(
            name=name,
            url=f"https://example.test/{name}.git",
            commit=commit,
            license="MIT",
            allowed_path="docs",
        ),
    )
    IndexStateStore(settings.index_state_path).save(identity)
    return settings


def test_evaluation_rejects_dataset_corpus_mismatch_before_retrieval(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            {
                "dataset": "fastapi-v1",
                "version": "1.1.0",
                "corpus": {"name": "fastapi", "commit": "fastapi-commit"},
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    settings = _active_profile_settings(tmp_path, "clippy", "clippy-commit")

    class GuardService(FakeService):
        def retrieve(self, _question: str, top_k: int = 5) -> list[SearchHit]:
            raise AssertionError("retrieval must not run for a corpus mismatch")

    service = GuardService()
    service.settings = settings
    with pytest.raises(DatasetValidationError, match="tracerag ingest"):
        run_evaluation(service, dataset, tmp_path / "reports")


def test_evaluation_uses_active_provenance_and_sanitizes_sources(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            {
                "dataset": "fastapi-v1",
                "version": "1.1.0",
                "corpus": {"name": "fastapi", "commit": "fastapi-commit"},
                "records": [
                    {
                        "id": "f01",
                        "question": "What is FastAPI?",
                        "in_scope": True,
                        "evidence_targets": [{"source": "docs/guide.md", "heading": "Intro"}],
                        "expected_facts": ["web framework"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settings = _active_profile_settings(tmp_path, "fastapi", "fastapi-commit")
    source = settings.corpus_path / "fastapi" / "docs" / "guide.md"

    class ProfileService(FakeService):
        def retrieve(self, _question: str, top_k: int = 5) -> list[SearchHit]:
            return [
                SearchHit(
                    Chunk("id", "FastAPI is a web framework.", str(source), 0, "Intro", "hash"),
                    0.9,
                    dense_score=0.9,
                )
            ]

    service = ProfileService()
    service.settings = settings
    report = run_evaluation(service, dataset, tmp_path / "reports")

    assert report["corpus"]["name"] == "fastapi"
    assert report["corpus"]["commit"] == "fastapi-commit"
    assert report["cases"][0]["sources"][0]["source"] == "docs/guide.md"
    assert "index_state_path" not in report["provenance"]
    assert not (tmp_path / "reports/latest.json").exists()


def test_sequential_datasets_write_distinct_report_files(tmp_path: Path) -> None:
    output = tmp_path / "reports"
    for name in ("fastapi-v1", "clippy-v1"):
        dataset = tmp_path / f"{name}.json"
        dataset.write_text(
            json.dumps({"dataset": name, "version": "1.1.0", "records": []}),
            encoding="utf-8",
        )
        run_evaluation(FakeService(), dataset, output)

    assert (output / "fastapi-v1.json").exists()
    assert (output / "fastapi-v1.md").exists()
    assert (output / "clippy-v1.json").exists()
    assert (output / "clippy-v1.md").exists()


def test_exact_target_matching_requires_source_and_heading() -> None:
    targets = [{"source": "docs/guide.md", "heading": "Intro"}]
    wrong_heading = [
        SearchHit(Chunk("id", "text", "/docs/guide.md", 0, "Other", "hash"), 0.9)
    ]
    wrong_file = [
        SearchHit(Chunk("id", "text", "/docs/other.md", 0, "Intro", "hash"), 0.9)
    ]

    assert match_evidence_targets(targets, wrong_heading) is None
    assert match_evidence_targets(targets, wrong_file) is None


def test_multiple_accepted_targets_match_within_top_five() -> None:
    targets = [
        {"source": "docs/first.md", "heading": "First"},
        {"source": "docs/guide.md", "heading": "Intro"},
    ]
    hits = [
        SearchHit(Chunk(str(i), "text", f"/docs/noise-{i}.md", 0, "Noise", "hash"), 0.9)
        for i in range(4)
    ]
    hits.append(SearchHit(Chunk("match", "text", "/docs/guide.md", 0, "Intro", "hash"), 0.5))

    assert match_evidence_targets(targets, hits) == {
        "source": "docs/guide.md",
        "heading": "intro",
        "rank": 5,
    }


def test_dataset_validation_rejects_missing_or_chunk_id_targets() -> None:
    base = {
        "dataset": "test",
        "version": "1.1.0",
        "records": [
            {
                "id": "case",
                "question": "Question?",
                "in_scope": True,
                "evidence_targets": [{"source": "docs/guide.md"}],
                "expected_facts": ["answer"],
            }
        ],
    }
    with pytest.raises(DatasetValidationError, match="heading"):
        validate_dataset(base)

    base["records"][0]["evidence_targets"] = [
        {"chunk_id": "unstable", "source": "docs/guide.md", "heading": "Intro"}
    ]
    with pytest.raises(DatasetValidationError, match="chunk_id"):
        validate_dataset(base)


def test_baseline_comparison_reports_only_regressions(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"metrics": {"recall_at_5": 0.9, "factuality": 1.0}}))

    assert compare_baseline({"metrics": {"recall_at_5": 0.8, "factuality": 1.0}}, baseline) == [
        "recall_at_5 regressed from 0.900 to 0.800"
    ]
