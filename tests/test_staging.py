from pathlib import Path

import chromadb
import pytest
from typer.testing import CliRunner

import tracerag.cli as cli_module
from tracerag.config import Settings
from tracerag.errors import PruneConfirmationRequired
from tracerag.generation_store import GenerationTransaction
from tracerag.index_state import CorpusProvenance, IndexStateStore
from tracerag.ingest import Ingestor
from tracerag.ollama import OllamaError
from tracerag.service import RAGService
from tracerag.source_state import SourceStateStore
from tracerag.store import BM25Store, VectorStore

runner = CliRunner()


class FakeOllama:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed(self, _model: str, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise OllamaError("synthetic embedding failure")
        return [[float(index + 1), 1.0] for index, _ in enumerate(texts)]


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, embed_batch_size=8)


def _ingestor(settings: Settings, ollama: FakeOllama) -> Ingestor:
    service = RAGService(settings)
    return Ingestor(settings, service.vectors, service.lexical, ollama)


def _write_documents(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    first = root / "first.md"
    second = root / "second.md"
    first.write_text("# First\n\nfirst evidence", encoding="utf-8")
    second.write_text("# Second\n\nsecond evidence", encoding="utf-8")
    return first, second


def test_successful_ingest_activates_matching_vector_and_bm25_generation(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, second = _write_documents(root)

    _ingestor(settings, FakeOllama()).ingest(root)

    state = IndexStateStore(settings.index_state_path).load()
    assert state is not None
    assert state.active_collection
    assert state.bm25_artifact
    active = RAGService(settings)
    assert active.vectors.collection_name == state.active_collection
    assert active.lexical.path == settings.data_dir / state.bm25_artifact
    assert {Path(chunk.source) for chunk in active.vectors.all_chunks()} == {first, second}
    assert active.lexical.load()


def test_successful_ingest_persists_generation_scoped_source_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    _write_documents(root)

    _ingestor(settings, FakeOllama()).ingest(root)

    state = IndexStateStore(settings.index_state_path).load()
    assert state is not None
    assert state.source_state_artifact
    source_state_path = settings.data_dir / state.source_state_artifact
    assert source_state_path.is_file()
    assert source_state_path != settings.source_state_path
    assert SourceStateStore(source_state_path).load()


def test_initial_all_empty_corpus_persists_authoritative_empty_source_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    empty = root / "empty.md"
    root.mkdir()
    empty.write_text("", encoding="utf-8")
    provenance = CorpusProvenance(
        name="fastapi",
        url="https://github.com/fastapi/fastapi.git",
        commit="f" * 40,
        license="MIT",
        allowed_path="docs/en/docs",
    )

    processed, chunks = _ingestor(settings, FakeOllama()).ingest(
        root,
        corpus_sha=provenance.commit,
        corpus_provenance=provenance,
    )

    assert (processed, chunks) == (1, 0)
    state = IndexStateStore(settings.index_state_path).load()
    assert state is not None
    assert state.embedding.dimension is None
    assert state.corpus_provenance == provenance
    monkeypatch.setattr(cli_module, "Settings", lambda **_: settings)
    result = runner.invoke(
        cli_module.app,
        ["documents", "--verbose"],
        color=False,
        terminal_width=240,
    )
    assert result.exit_code == 0
    documents = RAGService(settings).documents()
    assert documents == [
        {
            "source": str(empty),
            "chunks": 0,
            "content_hash": SourceStateStore.hash_file(empty),
            "source_hash": SourceStateStore.hash_file(empty),
            "relative_path": "empty.md",
            "status": "empty",
        }
    ]
    assert "empty" in result.output


def test_empty_generation_can_later_establish_embedding_dimension(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    empty = root / "empty.md"
    root.mkdir()
    empty.write_text("", encoding="utf-8")

    _ingestor(settings, FakeOllama()).ingest(root)
    empty.write_text("# Added later\n\nnew evidence", encoding="utf-8")

    _ingestor(settings, FakeOllama()).ingest(root)

    state = IndexStateStore(settings.index_state_path).load()
    assert state is not None
    assert state.embedding.dimension == 2
    documents = RAGService(settings).documents()
    assert documents[0]["status"] == "current"
    assert documents[0]["chunks"] > 0


def test_ingest_persists_path_bound_corpus_provenance(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    _write_documents(root)
    provenance = CorpusProvenance(
        name="fastapi",
        url="https://github.com/fastapi/fastapi.git",
        commit="f" * 40,
        license="MIT",
        allowed_path="docs/en/docs",
    )

    _ingestor(settings, FakeOllama()).ingest(
        root, corpus_sha=provenance.commit, corpus_provenance=provenance
    )

    state = IndexStateStore(settings.index_state_path).load()
    assert state is not None
    assert state.corpus_provenance == provenance


def test_failed_stage_preserves_old_generation_and_artifacts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, _ = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)

    old_state_bytes = settings.index_state_path.read_bytes()
    old_state = IndexStateStore(settings.index_state_path).load()
    assert old_state is not None
    old_active = RAGService(settings)
    old_chunks = old_active.vectors.all_chunks()
    old_bm25_bytes = old_active.lexical.path.read_bytes()
    first.write_text("# First\n\nchanged evidence", encoding="utf-8")

    with pytest.raises(OllamaError, match="synthetic embedding failure"):
        _ingestor(settings, FakeOllama(fail=True)).ingest(root)

    assert settings.index_state_path.read_bytes() == old_state_bytes
    assert old_active.lexical.path.read_bytes() == old_bm25_bytes
    current = RAGService(settings)
    assert current.vectors.all_chunks() == old_chunks
    assert current.lexical.load() == old_chunks
    assert current.vectors.collection_name == old_state.active_collection
    collections = chromadb.PersistentClient(path=str(settings.chroma_path)).list_collections()
    assert {collection.name for collection in collections} == {old_state.active_collection}


def test_failed_parse_preserves_old_generation(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, _ = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)
    old_state_bytes = settings.index_state_path.read_bytes()
    first.write_text("# First\n\nchanged evidence", encoding="utf-8")

    def fail_parse(*_args, **_kwargs):
        raise ValueError("synthetic parse failure")

    monkeypatch.setattr("tracerag.ingest.parse_document", fail_parse)
    with pytest.raises(ValueError, match="synthetic parse failure"):
        _ingestor(settings, FakeOllama()).ingest(root)

    assert settings.index_state_path.read_bytes() == old_state_bytes


def test_failed_bm25_write_preserves_old_generation(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, _ = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)
    old_state_bytes = settings.index_state_path.read_bytes()
    first.write_text("# First\n\nchanged evidence", encoding="utf-8")

    def fail_save(_self, _chunks):
        raise OSError("synthetic BM25 write failure")

    monkeypatch.setattr(BM25Store, "save", fail_save)
    with pytest.raises(OSError, match="synthetic BM25 write failure"):
        _ingestor(settings, FakeOllama()).ingest(root)

    assert settings.index_state_path.read_bytes() == old_state_bytes


def test_failed_source_state_write_preserves_old_generation(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, _ = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)
    old_state_bytes = settings.index_state_path.read_bytes()
    old_state = IndexStateStore(settings.index_state_path).load()
    assert old_state is not None
    old_chunks = RAGService(settings).vectors.all_chunks()
    old_bm25_bytes = (settings.data_dir / old_state.bm25_artifact).read_bytes()
    old_source_state_path = settings.data_dir / old_state.source_state_artifact
    old_source_state_bytes = old_source_state_path.read_bytes()
    first.write_text("# First\n\nchanged evidence", encoding="utf-8")

    def fail_source_state(_self, _records):
        raise OSError("synthetic source-state write failure")

    monkeypatch.setattr(SourceStateStore, "save", fail_source_state)
    with pytest.raises(OSError, match="synthetic source-state write failure"):
        _ingestor(settings, FakeOllama()).ingest(root)

    assert settings.index_state_path.read_bytes() == old_state_bytes
    assert old_source_state_path.read_bytes() == old_source_state_bytes
    assert (settings.data_dir / old_state.bm25_artifact).read_bytes() == old_bm25_bytes
    current = RAGService(settings)
    assert current.vectors.all_chunks() == old_chunks
    collections = chromadb.PersistentClient(path=str(settings.chroma_path)).list_collections()
    assert {collection.name for collection in collections} == {old_state.active_collection}


def test_failed_manifest_activation_preserves_old_generation(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, _ = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)
    old_state_bytes = settings.index_state_path.read_bytes()
    old_state = IndexStateStore(settings.index_state_path).load()
    assert old_state is not None
    old_chunks = RAGService(settings).vectors.all_chunks()
    first.write_text("# First\n\nchanged evidence", encoding="utf-8")

    def fail_manifest(_self, _identity):
        raise OSError("synthetic manifest activation failure")

    monkeypatch.setattr(IndexStateStore, "save", fail_manifest)
    with pytest.raises(OSError, match="synthetic manifest activation failure"):
        _ingestor(settings, FakeOllama()).ingest(root)

    assert settings.index_state_path.read_bytes() == old_state_bytes
    assert RAGService(settings).vectors.all_chunks() == old_chunks
    collections = chromadb.PersistentClient(path=str(settings.chroma_path)).list_collections()
    assert {collection.name for collection in collections} == {old_state.active_collection}


def test_failed_chroma_stage_preserves_old_generation(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, _ = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)
    old_state_bytes = settings.index_state_path.read_bytes()
    old_state = IndexStateStore(settings.index_state_path).load()
    assert old_state is not None
    old_chunks = RAGService(settings).vectors.all_chunks()
    first.write_text("# First\n\nchanged evidence", encoding="utf-8")

    def fail_replace(_self, _source, _chunks, _embeddings):
        raise OSError("synthetic Chroma staging failure")

    monkeypatch.setattr(VectorStore, "replace_source", fail_replace)
    with pytest.raises(OSError, match="synthetic Chroma staging failure"):
        _ingestor(settings, FakeOllama()).ingest(root)

    assert settings.index_state_path.read_bytes() == old_state_bytes
    assert RAGService(settings).vectors.all_chunks() == old_chunks
    collections = chromadb.PersistentClient(path=str(settings.chroma_path)).list_collections()
    assert {collection.name for collection in collections} == {old_state.active_collection}


def test_failed_generation_validation_preserves_old_generation(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, _ = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)
    old_state_bytes = settings.index_state_path.read_bytes()
    old_state = IndexStateStore(settings.index_state_path).load()
    assert old_state is not None
    old_chunks = RAGService(settings).vectors.all_chunks()
    first.write_text("# First\n\nchanged evidence", encoding="utf-8")

    def fail_validation(_prepared, _validate_collection=None):
        raise OSError("synthetic generation validation failure")

    monkeypatch.setattr(GenerationTransaction, "validate", staticmethod(fail_validation))
    with pytest.raises(OSError, match="synthetic generation validation failure"):
        _ingestor(settings, FakeOllama()).ingest(root)

    assert settings.index_state_path.read_bytes() == old_state_bytes
    assert RAGService(settings).vectors.all_chunks() == old_chunks
    collections = chromadb.PersistentClient(path=str(settings.chroma_path)).list_collections()
    assert {collection.name for collection in collections} == {old_state.active_collection}


def test_prune_requires_confirmation_and_then_removes_only_missing_source(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    root = tmp_path / "docs"
    first, second = _write_documents(root)
    _ingestor(settings, FakeOllama()).ingest(root)
    old_state = IndexStateStore(settings.index_state_path).load()
    assert old_state is not None
    second.unlink()

    _ingestor(settings, FakeOllama()).ingest(root)
    retained = RAGService(settings)
    assert {Path(chunk.source) for chunk in retained.vectors.all_chunks()} == {first, second}
    assert IndexStateStore(settings.index_state_path).load().generation == old_state.generation

    with pytest.raises(PruneConfirmationRequired) as pending:
        _ingestor(settings, FakeOllama()).ingest(root, prune=True)

    assert str(second) in str(pending.value)
    preview = RAGService(settings)
    assert {Path(chunk.source) for chunk in preview.vectors.all_chunks()} == {first, second}
    assert IndexStateStore(settings.index_state_path).load().generation == old_state.generation

    _ingestor(settings, FakeOllama()).ingest(root, prune=True, prune_confirmed=True)

    active = RAGService(settings)
    assert {Path(chunk.source) for chunk in active.vectors.all_chunks()} == {first}
    assert all(Path(chunk.source) != second for chunk in active.lexical.load())
