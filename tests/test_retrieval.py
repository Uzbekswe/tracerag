from pathlib import Path

from tracerag.models import Chunk
from tracerag.retrieval import Retriever
from tracerag.store import BM25Store, VectorStore


class FakeOllama:
    def embed(self, _model: str, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class FakeVectors:
    def query(self, _embedding: list[float], _top_k: int) -> list[tuple[Chunk, float]]:
        return [(Chunk("a", "error code ERR-42", "guide.md", 0, "Errors", "h"), 0.9)]

    def all_chunks(self) -> list[Chunk]:
        return [Chunk("a", "error code ERR-42", "guide.md", 0, "Errors", "h")]


def test_hybrid_retriever_keeps_dense_and_lexical_hit(tmp_path: Path) -> None:
    lexical = BM25Store(tmp_path / "bm25.json")
    lexical.save([Chunk("a", "error code ERR-42", "guide.md", 0, "Errors", "h")])
    hits = Retriever(FakeVectors(), lexical, FakeOllama(), "embed", 5).retrieve("ERR-42")
    assert hits
    assert hits[0].chunk.source == "guide.md"
    assert hits[0].dense_score > 0


def test_hybrid_retriever_prefers_substantive_evidence() -> None:
    tiny = Chunk("tiny", "FastAPI", "tiny.md", 0, "", "h")
    full = Chunk(
        "full",
        "FastAPI is a web framework for Python. " * 3,
        "full.md",
        0,
        "",
        "h",
    )

    class Vectors:
        def query(self, _embedding, _top_k):
            return [(tiny, 0.99), (full, 0.8)]

        def all_chunks(self):
            return [tiny, full]

    class Lexical:
        def load(self):
            return [tiny, full]

    hits = Retriever(Vectors(), Lexical(), FakeOllama(), "embed", 1).retrieve("FastAPI")
    assert hits[0].chunk.chunk_id == "full"


def test_vector_store_replaces_only_the_changed_source(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "chroma", "test")
    source_a = "a.md"
    source_b = "b.md"
    chunk_a1 = Chunk("a1", "old A", source_a, 0, "A", "hash-a1")
    chunk_a2 = Chunk("a2", "old A second", source_a, 1, "A", "hash-a2")
    chunk_b = Chunk("b1", "stable B", source_b, 0, "B", "hash-b")

    store.replace_source(source_a, [chunk_a1, chunk_a2], [[1.0, 0.0], [0.0, 1.0]])
    store.replace_source(source_b, [chunk_b], [[1.0, 1.0]])
    replacement = Chunk("a3", "new A", source_a, 0, "A", "hash-a3")
    store.replace_source(source_a, [replacement], [[0.5, 0.5]])

    chunks = store.all_chunks()
    assert {chunk.chunk_id for chunk in chunks} == {"a3", "b1"}
    assert next(chunk for chunk in chunks if chunk.chunk_id == "b1").text == "stable B"
