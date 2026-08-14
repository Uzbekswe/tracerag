from pathlib import Path

from tracerag.config import Settings
from tracerag.generation_store import GenerationTransaction, PreparedGeneration
from tracerag.index_state import CorpusProvenance, IndexStateStore
from tracerag.models import Chunk
from tracerag.source_state import SourceRecord, SourceStateStore
from tracerag.store import BM25Store, VectorStore


def _prepared(tmp_path: Path) -> PreparedGeneration:
    source = str((tmp_path / "guide.md").resolve())
    chunk = Chunk(
        "chunk-1",
        "reliable evidence",
        source,
        0,
        "Guide",
        "chunk-hash",
        source_hash="source-hash",
    )
    return PreparedGeneration(
        chunks=(chunk,),
        embeddings=((1.0, 0.0),),
        source_records={source: SourceRecord(source, "guide.md", "source-hash", "commit", 1)},
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        embedding_dimension=2,
        corpus_provenance=CorpusProvenance(
            name="fastapi",
            url="https://github.com/fastapi/fastapi.git",
            commit="commit",
            license="MIT",
            allowed_path="docs/en/docs",
        ),
    )


def test_transaction_activates_one_complete_generation(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    state_store = IndexStateStore(settings.index_state_path)

    outcome = GenerationTransaction(settings, state_store).execute(_prepared(tmp_path), None)

    state = state_store.load()
    assert state is not None
    assert state == outcome.identity
    assert state.active_collection
    assert VectorStore(settings.vector_path, state.active_collection).all_chunks()
    assert BM25Store(settings.data_dir / state.bm25_artifact).load()
    assert SourceStateStore(settings.data_dir / state.source_state_artifact).load()


def test_cleanup_failure_keeps_activation_and_reports_recoverable_leftover(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(data_dir=tmp_path)
    state_store = IndexStateStore(settings.index_state_path)
    first = GenerationTransaction(settings, state_store).execute(_prepared(tmp_path), None)

    def fail_delete(_self) -> None:
        raise OSError("synthetic cleanup failure")

    monkeypatch.setattr(VectorStore, "delete", fail_delete)
    second = GenerationTransaction(settings, state_store).execute(
        _prepared(tmp_path), first.identity
    )

    assert state_store.load() == second.identity
    assert second.warnings
    assert "recoverable leftover" in " ".join(second.warnings)
    assert VectorStore(settings.vector_path, second.identity.active_collection).count() == 1
