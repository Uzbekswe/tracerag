import json
from pathlib import Path

from tracerag.evaluation import compare_baseline, run_evaluation
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
                "records": [
                    {
                        "id": "in",
                        "question": "What is FastAPI?",
                        "in_scope": True,
                        "expected_sources": ["docs"],
                        "expected_facts": ["web framework"],
                    },
                    {
                        "id": "out",
                        "question": "What is outside?",
                        "in_scope": False,
                        "expected_sources": [],
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
    assert (tmp_path / "reports/latest.json").exists()
    assert (tmp_path / "reports/latest.md").exists()


def test_baseline_comparison_reports_only_regressions(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"metrics": {"recall_at_5": 0.9, "factuality": 1.0}}))

    assert compare_baseline({"metrics": {"recall_at_5": 0.8, "factuality": 1.0}}, baseline) == [
        "recall_at_5 regressed from 0.900 to 0.800"
    ]
