from pathlib import Path

import pytest

from tracerag.config import Settings
from tracerag.errors import ConcurrentIngestError, IncompatibleIndexError, LegacyIndexError
from tracerag.index_state import (
    CorpusProvenance,
    EmbeddingIdentity,
    IndexIdentity,
    IndexStateStore,
)
from tracerag.ingest import Ingestor
from tracerag.locking import ingest_lock
from tracerag.models import Chunk


class FakeVectors:
    def __init__(self, has_data: bool = False) -> None:
        self.has_existing_data = has_data
        self.reset_called = False
        self.replacements: list[tuple[str, list[Chunk], list[list[float]]]] = []

    def has_data(self) -> bool:
        return self.has_existing_data

    def reset(self) -> None:
        self.reset_called = True
        self.has_existing_data = False

    def replace_source(self, source, chunks, embeddings) -> None:
        self.replacements.append((source, chunks, embeddings))
        self.has_existing_data = bool(chunks)

    def all_chunks(self) -> list[Chunk]:
        return [chunk for _, chunks, _ in self.replacements for chunk in chunks]


class FakeLexical:
    def __init__(self, has_data: bool = False) -> None:
        self.has_existing_data = has_data
        self.clear_called = False

    def has_data(self) -> bool:
        return self.has_existing_data

    def clear(self) -> None:
        self.clear_called = True
        self.has_existing_data = False

    def save(self, chunks) -> None:
        self.has_existing_data = bool(chunks)


class FakeOllama:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, _model: str, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[1.0, 0.0] for _ in texts]


def _ingestor(
    tmp_path: Path,
    vectors: FakeVectors | None = None,
    lexical: FakeLexical | None = None,
    ollama: FakeOllama | None = None,
) -> tuple[Ingestor, FakeVectors, FakeLexical, FakeOllama]:
    vectors = vectors or FakeVectors()
    lexical = lexical or FakeLexical()
    ollama = ollama or FakeOllama()
    settings = Settings(data_dir=tmp_path)
    return Ingestor(settings, vectors, lexical, ollama), vectors, lexical, ollama


def test_lock_rejects_a_second_writer(tmp_path: Path) -> None:
    lock_path = tmp_path / "index.lock"

    with ingest_lock(lock_path), pytest.raises(
        ConcurrentIngestError, match="another ingest is already running"
    ), ingest_lock(lock_path):
        pass


def test_legacy_index_requires_explicit_rebuild_before_embedding(tmp_path: Path) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Guide\n\ncontent", encoding="utf-8")
    ingestor, _, _, ollama = _ingestor(
        tmp_path,
        vectors=FakeVectors(has_data=True),
        lexical=FakeLexical(has_data=True),
    )

    with pytest.raises(LegacyIndexError, match=r"tracerag ingest PATH --rebuild"):
        ingestor.ingest(source)

    assert ollama.calls == []


def test_invalid_manifest_requires_rebuild_and_rebuild_replaces_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Guide\n\ncontent", encoding="utf-8")
    settings = Settings(data_dir=tmp_path)
    settings.index_state_path.write_text('{"schema_version": 1}', encoding="utf-8")
    vectors = FakeVectors(has_data=True)
    lexical = FakeLexical(has_data=True)
    ollama = FakeOllama()
    ingestor = Ingestor(settings, vectors, lexical, ollama)

    with pytest.raises(IncompatibleIndexError, match=r"tracerag ingest PATH --rebuild"):
        ingestor.ingest(source)
    assert ollama.calls == []

    chunk = Chunk("chunk-1", "content", str(source), 0, "Guide", "content-hash")
    monkeypatch.setattr("tracerag.ingest.parse_document", lambda *_args, **_kwargs: [chunk])
    ingestor.ingest(source, rebuild=True)

    state = IndexStateStore(settings.index_state_path).load()
    assert state is not None
    assert state.schema_version == 2


def test_index_manifest_round_trips_typed_corpus_provenance(tmp_path: Path) -> None:
    state_store = IndexStateStore(tmp_path / "index-state.json")
    identity = IndexStateStore.new(
        collection="tracerag",
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        embedding_dimension=768,
        source_state_artifact="source-state/generations/generation.json",
        corpus_provenance=CorpusProvenance(
            name="fastapi",
            url="https://github.com/fastapi/fastapi.git",
            commit="abc123",
            license="MIT",
            allowed_path="docs/en/docs",
        ),
    )

    state_store.save(identity)

    loaded = state_store.load()
    assert loaded is not None
    assert loaded.corpus_provenance == identity.corpus_provenance


def test_rebuild_authorizes_legacy_replacement_and_writes_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Guide\n\ncontent", encoding="utf-8")
    ingestor, vectors, lexical, _ = _ingestor(
        tmp_path,
        vectors=FakeVectors(has_data=True),
        lexical=FakeLexical(has_data=True),
    )
    chunk = Chunk("chunk-1", "content", str(source), 0, "Guide", "content-hash")
    monkeypatch.setattr("tracerag.ingest.parse_document", lambda *_args, **_kwargs: [chunk])

    ingestor.ingest(source, rebuild=True)

    assert vectors.reset_called
    assert lexical.clear_called
    state = IndexStateStore(ingestor.settings.index_state_path).load()
    assert state is not None
    assert state.collection == ingestor.settings.collection
    assert state.embedding.model == ingestor.settings.embed_model
    assert state.embedding.dimension == 2
    assert state.generation


def test_incompatible_manifest_fails_before_embedding(tmp_path: Path) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Guide\n\ncontent", encoding="utf-8")
    ingestor, _, _, ollama = _ingestor(tmp_path)
    IndexStateStore(ingestor.settings.index_state_path).save(
        IndexIdentity(
            generation="old-generation",
            collection=ingestor.settings.collection,
            embedding=EmbeddingIdentity(provider="ollama", model="different-model", dimension=2),
            chunking_version="structural-v1",
            preprocessing_version="parser-v1",
        )
    )

    with pytest.raises(IncompatibleIndexError, match=r"tracerag ingest PATH --rebuild"):
        ingestor.ingest(source)

    assert ollama.calls == []


def test_incompatible_chunking_manifest_fails_before_embedding(tmp_path: Path) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Guide\n\ncontent", encoding="utf-8")
    ingestor, _, _, ollama = _ingestor(tmp_path)
    IndexStateStore(ingestor.settings.index_state_path).save(
        IndexIdentity(
            generation="old-generation",
            collection=ingestor.settings.collection,
            embedding=EmbeddingIdentity(
                provider="ollama", model=ingestor.settings.embed_model, dimension=2
            ),
            chunking_version="different-chunker",
            preprocessing_version="parser-v1",
        )
    )

    with pytest.raises(IncompatibleIndexError, match=r"tracerag ingest PATH --rebuild"):
        ingestor.ingest(source)

    assert ollama.calls == []


def test_rebuild_authorizes_incompatible_manifest_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Guide\n\ncontent", encoding="utf-8")
    ingestor, vectors, lexical, _ = _ingestor(
        tmp_path,
        vectors=FakeVectors(has_data=True),
        lexical=FakeLexical(has_data=True),
    )
    IndexStateStore(ingestor.settings.index_state_path).save(
        IndexIdentity(
            generation="old-generation",
            collection=ingestor.settings.collection,
            embedding=EmbeddingIdentity(provider="ollama", model="different-model", dimension=2),
            chunking_version="structural-v1",
            preprocessing_version="parser-v1",
        )
    )
    chunk = Chunk("chunk-1", "content", str(source), 0, "Guide", "content-hash")
    monkeypatch.setattr("tracerag.ingest.parse_document", lambda *_args, **_kwargs: [chunk])

    ingestor.ingest(source, rebuild=True)

    assert vectors.reset_called
    assert lexical.clear_called
    assert IndexStateStore(ingestor.settings.index_state_path).load().embedding.model == (
        ingestor.settings.embed_model
    )
