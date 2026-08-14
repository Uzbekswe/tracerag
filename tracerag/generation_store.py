from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .errors import (
    GenerationActivationError,
    GenerationStageError,
    GenerationValidationError,
)
from .index_state import CorpusProvenance, IndexIdentity, IndexStateStore
from .models import Chunk
from .source_state import SourceRecord, SourceStateStore
from .store import BM25Store, VectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedGeneration:
    """Complete immutable in-memory data eligible for one activation."""

    chunks: tuple[Chunk, ...]
    embeddings: tuple[tuple[float, ...], ...]
    source_records: dict[str, SourceRecord]
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int | None
    corpus_provenance: CorpusProvenance | None = None


@dataclass(frozen=True)
class GenerationOutcome:
    """The active identity and recoverable cleanup warnings after a commit."""

    identity: IndexIdentity
    warnings: tuple[str, ...] = ()


class GenerationTransaction:
    """Own every durable operation required to publish one complete generation."""

    def __init__(self, settings: Settings, state_store: IndexStateStore) -> None:
        self.settings = settings
        self.state_store = state_store

    def execute(
        self, prepared: PreparedGeneration, previous_state: IndexIdentity | None
    ) -> GenerationOutcome:
        generation = IndexStateStore.new_generation()
        collection = self._collection_name(generation)
        vector_store = VectorStore(self.settings.vector_path, collection)
        bm25_path = self.settings.bm25_generations_path / f"{generation}.json"
        source_state_path = self.settings.source_state_generations_path / f"{generation}.json"
        identity = IndexStateStore.new(
            collection=self.settings.collection,
            embedding_provider=prepared.embedding_provider,
            embedding_model=prepared.embedding_model,
            embedding_dimension=prepared.embedding_dimension,
            generation=generation,
            active_collection=collection,
            bm25_artifact=(Path("bm25") / "generations" / f"{generation}.json").as_posix(),
            source_state_artifact=(
                Path("source-state") / "generations" / f"{generation}.json"
            ).as_posix(),
            corpus_provenance=prepared.corpus_provenance,
        )
        bm25 = BM25Store(bm25_path)
        source_state = SourceStateStore(source_state_path)
        previous_manifest = self._manifest_bytes()
        committed = False
        try:
            self._write_stage(vector_store, bm25, source_state, prepared)
            self._validate_stage(vector_store, bm25, source_state, prepared, identity)
            try:
                self.state_store.save(identity)
                committed = True
            except BaseException as exc:
                self._restore_manifest(previous_manifest)
                raise GenerationActivationError(
                    f"could not activate generation {generation}: {exc}"
                ) from exc
        except GenerationActivationError:
            self._discard_stage(vector_store, bm25_path, source_state_path)
            raise
        except GenerationValidationError:
            self._discard_stage(vector_store, bm25_path, source_state_path)
            raise
        except BaseException as exc:
            self._discard_stage(vector_store, bm25_path, source_state_path)
            raise GenerationStageError(
                f"could not stage generation {generation}: {exc}"
            ) from exc

        if not committed:  # pragma: no cover - defensive guard
            raise GenerationActivationError("generation activation did not commit")
        warnings = self._cleanup_previous(previous_state, identity)
        for warning in warnings:
            logger.warning(warning)
        return GenerationOutcome(identity, tuple(warnings))

    def _write_stage(
        self,
        vector_store: VectorStore,
        bm25: BM25Store,
        source_state: SourceStateStore,
        prepared: PreparedGeneration,
    ) -> None:
        chunks = list(prepared.chunks)
        embeddings = [list(vector) for vector in prepared.embeddings]
        vector_store.import_chunks(chunks, embeddings)
        bm25.save(chunks)
        source_state.save(prepared.source_records)

    @staticmethod
    def _validate_stage(
        vector_store: VectorStore,
        bm25: BM25Store,
        source_state: SourceStateStore,
        prepared: PreparedGeneration,
        identity: IndexIdentity,
    ) -> None:
        try:
            vector_store.validate(
                prepared.embedding_dimension,
                expected_collection=identity.active_collection,
            )
            if vector_store.count() != len(prepared.chunks):
                raise ValueError("vector count does not match the prepared generation")
            bm25.validate(len(prepared.chunks))
            source_state.validate()
            records = source_state.load()
            if records != prepared.source_records:
                raise ValueError("source-state records do not match the prepared generation")
            if sum(record.chunk_count for record in records.values()) != len(prepared.chunks):
                raise ValueError("source-state chunk counts do not match the vector generation")
            known_sources = set(records)
            if any(chunk.source not in known_sources for chunk in prepared.chunks):
                raise ValueError("vector generation contains an unknown source")
            if identity.active_collection != vector_store.collection_name:
                raise ValueError("active vector generation identity does not match")
            if identity.embedding.dimension != prepared.embedding_dimension:
                raise ValueError("embedding identity does not match the prepared generation")
        except GenerationValidationError:
            raise
        except BaseException as exc:
            raise GenerationValidationError(f"staged generation validation failed: {exc}") from exc

    def _cleanup_previous(
        self, previous_state: IndexIdentity | None, active_identity: IndexIdentity
    ) -> list[str]:
        if previous_state is None:
            warnings: list[str] = []
            legacy_path = self.settings.vector_path / f"{self.settings.collection}.sqlite3"
            if legacy_path != self.settings.vector_path / f"{active_identity.active_collection}.sqlite3":
                try:
                    legacy_path.unlink(missing_ok=True)
                except OSError as exc:  # pragma: no cover - exercised through injection
                    warnings.append(
                        "could not clean the unversioned vector index; "
                        f"recoverable leftover retained: {exc}"
                    )
            return warnings
        warnings: list[str] = []
        old_collection = previous_state.active_collection
        if old_collection and old_collection != active_identity.active_collection:
            try:
                VectorStore(self.settings.vector_path, old_collection).delete()
            except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
                warnings.append(
                    f"could not clean previous vector generation {old_collection}; "
                    f"recoverable leftover retained: {exc}"
                )
        for label, artifact in (
            ("BM25", previous_state.bm25_artifact),
            ("source-state", previous_state.source_state_artifact),
        ):
            if not artifact:
                continue
            try:
                path = self._artifact_path(artifact)
                path.unlink(missing_ok=True)
            except (OSError, ValueError) as exc:  # pragma: no cover - exercised through injection
                warnings.append(
                    f"could not clean previous {label} generation; "
                    f"recoverable leftover retained: {exc}"
                )
        return warnings

    def _artifact_path(self, artifact: str) -> Path:
        path = Path(artifact)
        if path.is_absolute():
            return path
        candidate = (self.settings.data_dir / path).resolve()
        candidate.relative_to(self.settings.data_dir.resolve())
        return candidate

    def _collection_name(self, generation: str) -> str:
        return f"{self.settings.collection[:32]}__{generation[:16]}"

    def _manifest_bytes(self) -> bytes | None:
        try:
            return self.state_store.path.read_bytes()
        except FileNotFoundError:
            return None

    def _restore_manifest(self, content: bytes | None) -> None:
        path = self.state_store.path
        if content is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".restore", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _discard_stage(vector_store: VectorStore, bm25_path: Path, source_state_path: Path) -> None:
        try:
            vector_store.delete()
        except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - cleanup warning
            logger.warning("could not remove failed vector stage; recoverable leftover retained: %s", exc)
        finally:
            for path in (bm25_path, source_state_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:  # pragma: no cover - cleanup warning
                    logger.warning(
                        "could not remove failed artifact %s; recoverable leftover retained: %s",
                        path,
                        exc,
                    )
