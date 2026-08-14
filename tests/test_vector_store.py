from pathlib import Path

import pytest

from tracerag.models import Chunk
from tracerag.store import VectorStore


def _chunks(tmp_path: Path) -> tuple[list[Chunk], list[list[float]]]:
    source = str((tmp_path / "guide.md").resolve())
    chunks = [
        Chunk("a", "alpha evidence", source, 0, "Alpha", "hash-a", source_hash="source"),
        Chunk("b", "beta evidence", source, 1, "Beta", "hash-b", source_hash="source"),
    ]
    return chunks, [[1.0, 0.0], [0.0, 1.0]]


def test_vector_store_round_trips_metadata_and_queries(tmp_path: Path) -> None:
    chunks, embeddings = _chunks(tmp_path)
    store = VectorStore(tmp_path / "vectors", "generation-1")

    store.import_chunks(chunks, embeddings)

    assert store.count() == 2
    store.validate(expected_dimension=2)
    exported_chunks, exported_embeddings = store.export()
    assert exported_chunks == chunks
    assert exported_embeddings == embeddings
    hits = store.query([1.0, 0.0], top_k=1)
    assert [(chunk.chunk_id, score) for chunk, score in hits] == [("a", 1.0)]


def test_vector_store_replaces_source_and_deletes_generation(tmp_path: Path) -> None:
    chunks, embeddings = _chunks(tmp_path)
    store = VectorStore(tmp_path / "vectors", "generation-1")
    store.import_chunks(chunks, embeddings)
    replacement = Chunk("c", "replacement evidence", chunks[0].source, 0, "Replacement", "hash-c")

    store.replace_source(replacement.source, [replacement], [[0.5, 0.5]])

    assert [chunk.chunk_id for chunk in store.all_chunks()] == ["c"]
    store.delete()
    assert not store.path.exists()


def test_vector_store_rejects_dimension_mismatch(tmp_path: Path) -> None:
    chunks, _ = _chunks(tmp_path)
    store = VectorStore(tmp_path / "vectors", "generation-1")
    store.import_chunks(chunks, [[1.0, 0.0], [0.0, 1.0]])

    with pytest.raises(ValueError, match="dimension"):
        store.import_chunks(chunks, [[1.0], [0.0]])
