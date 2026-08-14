from pathlib import Path

from tracerag.cache import EmbeddingCache
from tracerag.config import Settings
from tracerag.ingest import Ingestor
from tracerag.models import Chunk
from tracerag.service import RAGService
from tracerag.source_state import ChangePlanner, SourceRecord, SourceStateStore


class FakeVectors:
    def __init__(self) -> None:
        self.replacements: list[tuple[str, list[Chunk], list[list[float]]]] = []

    def has_data(self) -> bool:
        return bool(self.replacements)

    def export(self):
        embeddings = [
            embedding
            for _, _, source_embeddings in self.replacements
            for embedding in source_embeddings
        ]
        return self.all_chunks(), embeddings

    def replace_source(self, source, chunks, embeddings) -> None:
        self.replacements.append((source, chunks, embeddings))

    def all_chunks(self) -> list[Chunk]:
        return [chunk for _, chunks, _ in self.replacements for chunk in chunks]


class FakeLexical:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []

    def has_data(self) -> bool:
        return bool(self.chunks)

    def save(self, chunks) -> None:
        self.chunks = list(chunks)


class FakeOllama:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, _model: str, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


def _chunk(source: Path, index: int, text: str, content_hash: str) -> Chunk:
    return Chunk(
        chunk_id=f"chunk-{source.name}-{index}",
        text=text,
        source=str(source.resolve()),
        chunk_index=index,
        heading_path="Guide",
        content_hash=content_hash,
        source_hash="source-hash",
    )


def _ingestor(tmp_path: Path) -> tuple[Ingestor, FakeVectors, FakeLexical, FakeOllama]:
    vectors = FakeVectors()
    lexical = FakeLexical()
    ollama = FakeOllama()
    return (
        Ingestor(Settings(data_dir=tmp_path), vectors, lexical, ollama),
        vectors,
        lexical,
        ollama,
    )


def test_change_planner_classifies_current_and_missing_sources(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    unchanged = root / "unchanged.md"
    changed = root / "changed.md"
    unsupported = root / "image.png"
    unchanged.write_text("same", encoding="utf-8")
    changed.write_text("new", encoding="utf-8")
    unsupported.write_bytes(b"png")
    missing = root / "missing.md"
    records = {
        str(unchanged.resolve()): SourceRecord(
            source=str(unchanged.resolve()),
            relative_path="unchanged.md",
            source_hash=SourceStateStore.hash_file(unchanged),
            corpus_sha="corpus",
            chunk_count=1,
        ),
        str(changed.resolve()): SourceRecord(
            source=str(changed.resolve()),
            relative_path="changed.md",
            source_hash="old-hash",
            corpus_sha="corpus",
            chunk_count=1,
        ),
        str(missing.resolve()): SourceRecord(
            source=str(missing.resolve()),
            relative_path="missing.md",
            source_hash="missing-hash",
            corpus_sha="corpus",
            chunk_count=1,
        ),
    }

    changes = ChangePlanner.plan(
        [unchanged, changed, unsupported], records, root, corpus_sha="corpus"
    )

    assert {change.status for change in changes} == {
        "unchanged",
        "changed",
        "unsupported",
        "missing",
    }
    assert next(change for change in changes if change.path == unchanged).status == "unchanged"
    assert next(change for change in changes if change.path == changed).status == "changed"


def test_unchanged_ingest_skips_parse_embedding_and_writes(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("same", encoding="utf-8")
    ingestor, _, _, ollama = _ingestor(tmp_path)
    parsed = [_chunk(source, 0, "same", "same-hash")]
    monkeypatch.setattr("tracerag.ingest.parse_document", lambda *_args, **_kwargs: parsed)

    assert ingestor.ingest(source) == (1, 1)
    first_call_count = len(ollama.calls)

    def fail_parse(*_args, **_kwargs):
        raise AssertionError("unchanged files must not be parsed")

    monkeypatch.setattr("tracerag.ingest.parse_document", fail_parse)
    assert ingestor.ingest(source) == (0, 0)

    assert len(ollama.calls) == first_call_count
    assert RAGService(Settings(data_dir=tmp_path)).lexical.load() == parsed


def test_changed_source_only_replaces_that_source(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    ingestor, _, _, ollama = _ingestor(tmp_path)
    chunks = {
        first: [_chunk(first, 0, "first", "first-hash")],
        second: [_chunk(second, 0, "second", "second-hash")],
    }
    monkeypatch.setattr(
        "tracerag.ingest.parse_document", lambda path, *_args, **_kwargs: chunks[path]
    )

    assert ingestor.ingest(tmp_path) == (2, 2)
    first_call_count = len(ollama.calls)
    first.write_text("first changed", encoding="utf-8")
    chunks[first] = [_chunk(first, 0, "first changed", "first-changed-hash")]

    assert ingestor.ingest(tmp_path) == (1, 1)
    assert len(ollama.calls) == first_call_count + 1
    active = RAGService(Settings(data_dir=tmp_path)).vectors.all_chunks()
    assert {chunk.source for chunk in active} == {str(first.resolve()), str(second.resolve())}
    assert next(chunk for chunk in active if chunk.source == str(first.resolve())).text == "first changed"


def test_changed_file_reuses_identical_chunk_embeddings(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "guide.md"
    source.write_text("guide", encoding="utf-8")
    ingestor, _, _, ollama = _ingestor(tmp_path)
    chunks = [_chunk(source, 0, "stable", "stable-hash")]
    monkeypatch.setattr("tracerag.ingest.parse_document", lambda *_args, **_kwargs: chunks)
    ingestor.ingest(source)

    source.write_text("guide changed", encoding="utf-8")
    chunks[:] = [
        _chunk(source, 0, "stable", "stable-hash"),
        _chunk(source, 1, "new", "new-hash"),
    ]
    ingestor.ingest(source)

    assert len(ollama.calls) == 2
    assert len(ollama.calls[-1]) == 1
    assert ollama.calls[-1][0].endswith("new")


def test_embedding_cache_identity_and_corruption_are_fail_open(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "cache", max_bytes=1024 * 1024)
    cache.put("text-hash", "nomic", 2, "chunk-v1", "parser-v1", [1.0, 2.0])

    assert cache.get("text-hash", "nomic", 2, "chunk-v1", "parser-v1") == [1.0, 2.0]
    assert cache.get("text-hash", "nomic", 3, "chunk-v1", "parser-v1") is None
    assert cache.get("text-hash", "other-model", 2, "chunk-v1", "parser-v1") is None
    assert cache.get("text-hash", "nomic", 2, "other-chunker", "parser-v1") is None
    assert cache.get("text-hash", "nomic", 2, "chunk-v1", "other-parser") is None

    entry = next((tmp_path / "cache").glob("*.json"))
    entry.write_text("not json", encoding="utf-8")
    assert cache.get("text-hash", "nomic", 2, "chunk-v1", "parser-v1") is None


def test_embedding_cache_lru_eviction_and_clear(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "cache", max_bytes=300)
    cache.put("first", "nomic", 2, "chunk-v1", "parser-v1", [1.0, 2.0])
    cache.put("second", "nomic", 2, "chunk-v1", "parser-v1", [3.0, 4.0])

    status = cache.status()
    assert status.entries == 1
    assert status.bytes <= status.max_bytes
    assert cache.get("first", "nomic", 2, "chunk-v1", "parser-v1") is None
    assert cache.get("second", "nomic", 2, "chunk-v1", "parser-v1") == [3.0, 4.0]

    assert cache.clear() == 1
    assert cache.status().entries == 0
