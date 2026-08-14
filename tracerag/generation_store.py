from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .index_state import CorpusProvenance, IndexIdentity, IndexStateStore
from .source_state import SourceRecord, SourceStateStore


@dataclass(frozen=True)
class PreparedGeneration:
    """The durable artifacts that are eligible for one manifest activation."""

    identity: IndexIdentity
    bm25_path: Path
    source_state_path: Path


class GenerationTransaction:
    """Stage and atomically activate a complete index generation."""

    def __init__(self, settings: Settings, state_store: IndexStateStore) -> None:
        self.settings = settings
        self.state_store = state_store

    def prepare(
        self,
        *,
        generation: str,
        collection_name: str,
        bm25_path: Path,
        source_records: dict[str, SourceRecord],
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
        corpus_provenance: CorpusProvenance | None = None,
    ) -> PreparedGeneration:
        source_state_path = self.settings.source_state_generations_path / f"{generation}.json"
        SourceStateStore(source_state_path).save(source_records)
        artifact = Path("bm25") / "generations" / f"{generation}.json"
        source_artifact = Path("source-state") / "generations" / f"{generation}.json"
        identity = IndexStateStore.new(
            collection=self.settings.collection,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            generation=generation,
            active_collection=collection_name,
            bm25_artifact=artifact.as_posix(),
            source_state_artifact=source_artifact.as_posix(),
            corpus_provenance=corpus_provenance,
        )
        prepared = PreparedGeneration(identity, bm25_path, source_state_path)
        return prepared

    @staticmethod
    def validate(prepared: PreparedGeneration, validate_collection: Callable[[], None] | None = None) -> None:
        if not prepared.bm25_path.is_file():
            raise OSError(f"staged BM25 artifact is missing: {prepared.bm25_path}")
        if not prepared.source_state_path.is_file():
            raise OSError(f"staged source state is missing: {prepared.source_state_path}")
        try:
            bm25 = json.loads(prepared.bm25_path.read_text(encoding="utf-8"))
            SourceStateStore(prepared.source_state_path).validate()
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise OSError("staged generation contains invalid JSON") from exc
        if not isinstance(bm25, list):
            raise OSError("staged BM25 artifact must contain a list")
        if not prepared.identity.source_state_artifact:
            raise OSError("staged source state has an invalid schema")
        if validate_collection is not None:
            validate_collection()

    def activate(
        self,
        prepared: PreparedGeneration,
        validate_collection: Callable[[], None] | None = None,
    ) -> None:
        self.validate(prepared, validate_collection)
        self.state_store.save(prepared.identity)

    @staticmethod
    def discard(prepared: PreparedGeneration | None) -> None:
        if prepared is None:
            return
        prepared.source_state_path.unlink(missing_ok=True)
