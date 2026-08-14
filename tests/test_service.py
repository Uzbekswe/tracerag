from pathlib import Path

from tracerag.config import Settings
from tracerag.ingest import Ingestor
from tracerag.models import Chunk, SearchHit
from tracerag.service import RAGService


def test_refusal_does_not_require_generation_model(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path, min_retrieval_score=0.95)
    service = RAGService(settings)
    monkeypatch.setattr(
        service,
        "retrieve",
        lambda _question, top_k=None: [
            SearchHit(Chunk("a", "unrelated", "guide.md", 0, "", "h"), 0.01, dense_score=0.1)
        ],
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("generator must not run on weak evidence")

    monkeypatch.setattr(service.generator, "answer", fail)
    result = service.ask("unsupported")
    assert result.refused
    assert "threshold" in (result.refusal_reason or "")


def test_ask_can_reuse_retrieved_hits(tmp_path: Path, monkeypatch) -> None:
    service = RAGService(Settings(data_dir=tmp_path, min_retrieval_score=0.95))
    hits = [SearchHit(Chunk("a", "unrelated", "guide.md", 0, "", "h"), 0.01)]
    monkeypatch.setattr(
        service, "retrieve", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())
    )

    result = service.ask("unsupported", hits=hits)

    assert result.refused


def test_refusal_rejects_semantically_related_but_uncovered_terms(tmp_path: Path) -> None:
    service = RAGService(Settings(data_dir=tmp_path, min_retrieval_score=0.5))
    hit = SearchHit(
        Chunk("a", "FastAPI security uses external libraries.", "guide.md", 0, "", "h"),
        0.01,
        dense_score=0.8,
        lexical_score=0.8,
    )

    assert not service._question_supported("What is the private database password?", [hit])


def test_high_score_but_uncovered_question_skips_generation(tmp_path: Path, monkeypatch) -> None:
    service = RAGService(Settings(data_dir=tmp_path, min_retrieval_score=0.5))
    hit = SearchHit(
        Chunk("a", "FastAPI security uses external libraries.", "guide.md", 0, "", "h"),
        0.01,
        dense_score=0.8,
        lexical_score=0.8,
    )
    monkeypatch.setattr(service, "retrieve", lambda *_args, **_kwargs: [hit])
    monkeypatch.setattr(
        service.generator,
        "answer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generation must be skipped")
        ),
    )

    result = service.ask("What is the private database password?")

    assert result.refused


class _IngestOllama:
    def embed(self, _model: str, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_documents_uses_source_state_for_empty_parsed_files(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "guide.md").write_text("# Guide\n\nUseful evidence.", encoding="utf-8")
    (root / "newsletter.md").write_text(
        "<html><body><!-- presentation only --></body></html>", encoding="utf-8"
    )
    settings = Settings(data_dir=tmp_path / "data")
    service = RAGService(settings)
    ingestor = Ingestor(settings, service.vectors, service.lexical, _IngestOllama())

    ingestor.ingest(root, rebuild=True)

    documents = RAGService(settings).documents()
    newsletter = next(item for item in documents if item["source"].endswith("newsletter.md"))
    assert newsletter["chunks"] == 0
    assert newsletter["status"] == "empty"
    assert ingestor.last_summary is not None
    assert ingestor.last_summary.indexed_with_chunks == 1
    assert ingestor.last_summary.empty == 1
