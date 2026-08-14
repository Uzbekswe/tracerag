from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .errors import IncompatibleIndexError, LegacyIndexError
from .persistence import atomic_write_json

INDEX_SCHEMA_VERSION = 2
CHUNKING_VERSION = "structural-v1"
PREPROCESSING_VERSION = "parser-v1"


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model: str
    dimension: int

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
        }

    @classmethod
    def from_dict(cls, value: object) -> EmbeddingIdentity:
        if not isinstance(value, dict):
            raise TypeError("embedding identity must be an object")
        provider = value.get("provider")
        model = value.get("model")
        dimension = value.get("dimension")
        if not isinstance(provider, str) or not provider:
            raise ValueError("embedding provider is missing")
        if not isinstance(model, str) or not model:
            raise ValueError("embedding model is missing")
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise ValueError("embedding dimension must be a positive integer")
        return cls(provider, model, dimension)


@dataclass(frozen=True)
class CorpusProvenance:
    name: str
    url: str
    commit: str
    license: str
    allowed_path: str
    fetched_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "url": self.url,
            "commit": self.commit,
            "license": self.license,
            "allowed_path": self.allowed_path,
        }
        if self.fetched_at is not None:
            payload["fetched_at"] = self.fetched_at
        return payload

    @classmethod
    def from_dict(cls, value: object) -> CorpusProvenance:
        if not isinstance(value, dict):
            raise TypeError("corpus provenance must be an object")
        fields = ("name", "url", "commit", "license", "allowed_path")
        values = {field: value.get(field) for field in fields}
        if not all(isinstance(item, str) and item for item in values.values()):
            raise ValueError("corpus provenance has missing identity fields")
        fetched_at = value.get("fetched_at")
        if fetched_at is not None and (not isinstance(fetched_at, str) or not fetched_at):
            raise ValueError("corpus provenance fetch time must be text")
        return cls(**values, fetched_at=fetched_at)


@dataclass(frozen=True)
class IndexIdentity:
    generation: str
    collection: str
    embedding: EmbeddingIdentity
    chunking_version: str
    preprocessing_version: str
    schema_version: int = INDEX_SCHEMA_VERSION
    active_collection: str | None = None
    bm25_artifact: str | None = None
    source_state_artifact: str | None = None
    corpus_provenance: CorpusProvenance | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "generation": self.generation,
            "collection": self.collection,
            "embedding": self.embedding.as_dict(),
            "chunking_version": self.chunking_version,
            "preprocessing_version": self.preprocessing_version,
        }
        if self.active_collection is not None:
            payload["active_collection"] = self.active_collection
        if self.bm25_artifact is not None:
            payload["bm25_artifact"] = self.bm25_artifact
        if self.source_state_artifact is not None:
            payload["source_state_artifact"] = self.source_state_artifact
        if self.corpus_provenance is not None:
            payload["corpus_provenance"] = self.corpus_provenance.as_dict()
        return payload

    @classmethod
    def from_dict(cls, value: object) -> IndexIdentity:
        if not isinstance(value, dict):
            raise TypeError("index state must be an object")
        schema_version = value.get("schema_version")
        generation = value.get("generation")
        collection = value.get("collection")
        chunking_version = value.get("chunking_version")
        preprocessing_version = value.get("preprocessing_version")
        active_collection = value.get("active_collection")
        bm25_artifact = value.get("bm25_artifact")
        source_state_artifact = value.get("source_state_artifact")
        corpus_provenance = value.get("corpus_provenance")
        if schema_version != INDEX_SCHEMA_VERSION:
            raise ValueError(f"unsupported index schema version: {schema_version!r}")
        if not isinstance(generation, str) or not generation:
            raise ValueError("index generation is missing")
        if not isinstance(collection, str) or not collection:
            raise ValueError("index collection is missing")
        if not isinstance(chunking_version, str) or not chunking_version:
            raise ValueError("chunking version is missing")
        if not isinstance(preprocessing_version, str) or not preprocessing_version:
            raise ValueError("preprocessing version is missing")
        if active_collection is not None and (
            not isinstance(active_collection, str) or not active_collection
        ):
            raise ValueError("active collection must be text")
        if bm25_artifact is not None and (
            not isinstance(bm25_artifact, str) or not bm25_artifact
        ):
            raise ValueError("BM25 artifact must be text")
        if source_state_artifact is not None and (
            not isinstance(source_state_artifact, str) or not source_state_artifact
        ):
            raise ValueError("source-state artifact must be text")
        parsed_provenance = (
            CorpusProvenance.from_dict(corpus_provenance)
            if corpus_provenance is not None
            else None
        )
        return cls(
            generation=generation,
            collection=collection,
            embedding=EmbeddingIdentity.from_dict(value.get("embedding")),
            chunking_version=chunking_version,
            preprocessing_version=preprocessing_version,
            schema_version=schema_version,
            active_collection=active_collection,
            bm25_artifact=bm25_artifact,
            source_state_artifact=source_state_artifact,
            corpus_provenance=parsed_provenance,
        )


class IndexStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> IndexIdentity | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return IndexIdentity.from_dict(value)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise IncompatibleIndexError(
                "the index state manifest is invalid; run "
                "tracerag ingest PATH --rebuild"
            ) from exc

    def save(self, identity: IndexIdentity) -> None:
        atomic_write_json(self.path, identity.as_dict())

    @staticmethod
    def new_generation() -> str:
        return uuid4().hex

    @staticmethod
    def resolve_active_storage(
        *,
        data_dir: Path,
        state_path: Path,
        default_collection: str,
        default_bm25_path: Path,
    ) -> tuple[str, Path]:
        """Resolve the active generation while keeping legacy v1 paths usable."""

        try:
            identity = IndexStateStore(state_path).load()
        except IncompatibleIndexError:
            return default_collection, default_bm25_path
        if identity is None:
            return default_collection, default_bm25_path
        collection = identity.active_collection or default_collection
        if not identity.bm25_artifact:
            return collection, default_bm25_path
        artifact = Path(identity.bm25_artifact)
        if artifact.is_absolute():
            return collection, artifact
        resolved = (data_dir / artifact).resolve()
        try:
            resolved.relative_to(data_dir.resolve())
        except ValueError:
            return collection, default_bm25_path
        return collection, resolved

    @staticmethod
    def resolve_source_state_path(
        *, data_dir: Path, state: IndexIdentity | None, legacy_path: Path
    ) -> Path:
        """Resolve source state from the active generation, with a v1 fallback."""
        if state is None or not state.source_state_artifact:
            return legacy_path
        artifact = (data_dir / state.source_state_artifact).resolve()
        try:
            artifact.relative_to(data_dir.resolve())
        except ValueError:
            return legacy_path
        return artifact

    def validate(
        self,
        *,
        collection: str,
        embedding_provider: str,
        embedding_model: str,
        chunking_version: str,
        preprocessing_version: str,
        legacy_index: bool,
        rebuild: bool,
    ) -> IndexIdentity | None:
        try:
            identity = self.load()
        except IncompatibleIndexError:
            if rebuild:
                return None
            raise
        if identity is None:
            if legacy_index and not rebuild:
                raise LegacyIndexError(
                    "an unversioned legacy index was found; run "
                    "tracerag ingest PATH --rebuild"
                )
            return None
        if rebuild:
            return identity
        mismatches: list[str] = []
        if identity.collection != collection:
            mismatches.append("collection")
        if identity.embedding.provider != embedding_provider:
            mismatches.append("embedding provider")
        if identity.embedding.model != embedding_model:
            mismatches.append("embedding model")
        if identity.chunking_version != chunking_version:
            mismatches.append("chunking version")
        if identity.preprocessing_version != preprocessing_version:
            mismatches.append("preprocessing version")
        if mismatches:
            joined = ", ".join(mismatches)
            raise IncompatibleIndexError(
                f"index identity is incompatible ({joined}); run "
                "tracerag ingest PATH --rebuild"
            )
        return identity

    @staticmethod
    def new(
        *,
        collection: str,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
        chunking_version: str = CHUNKING_VERSION,
        preprocessing_version: str = PREPROCESSING_VERSION,
        generation: str | None = None,
        active_collection: str | None = None,
        bm25_artifact: str | None = None,
        source_state_artifact: str | None = None,
        corpus_provenance: CorpusProvenance | None = None,
    ) -> IndexIdentity:
        return IndexIdentity(
            generation=generation or IndexStateStore.new_generation(),
            collection=collection,
            embedding=EmbeddingIdentity(
                provider=embedding_provider,
                model=embedding_model,
                dimension=embedding_dimension,
            ),
            chunking_version=chunking_version,
            preprocessing_version=preprocessing_version,
            active_collection=active_collection,
            bm25_artifact=bm25_artifact,
            source_state_artifact=source_state_artifact,
            corpus_provenance=corpus_provenance,
        )
