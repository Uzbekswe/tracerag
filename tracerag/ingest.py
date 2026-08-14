from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .cache import EmbeddingCache
from .config import Settings
from .corpus import resolve_corpus_context
from .errors import IncompatibleIndexError, PruneConfirmationRequired
from .generation_store import GenerationTransaction, PreparedGeneration
from .index_state import CHUNKING_VERSION, PREPROCESSING_VERSION, CorpusProvenance, IndexStateStore
from .locking import ingest_lock
from .models import Chunk
from .ollama import OllamaClient, OllamaError
from .parsers import parse_document
from .source_state import ChangePlanner, FileChange, SourceRecord, SourceStateStore
from .store import BM25Store, VectorStore

logger = logging.getLogger(__name__)
Reporter = Callable[[str, dict[str, object]], None]


@dataclass(frozen=True)
class IngestSummary:
    discovered: int = 0
    indexed: int = 0
    indexed_with_chunks: int = 0
    empty: int = 0
    changed: int = 0
    skipped: int = 0
    missing: int = 0
    pruned: int = 0
    unsupported: int = 0
    chunks_embedded: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    active_generation: str | None = None
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "discovered": self.discovered,
            "indexed": self.indexed,
            "indexed_with_chunks": self.indexed_with_chunks,
            "empty": self.empty,
            "changed": self.changed,
            "skipped": self.skipped,
            "missing": self.missing,
            "pruned": self.pruned,
            "unsupported": self.unsupported,
            "chunks_embedded": self.chunks_embedded,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "active_generation": self.active_generation,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


class Ingestor:
    def __init__(
        self, settings: Settings, vectors: VectorStore, lexical: BM25Store, ollama: OllamaClient
    ) -> None:
        self.settings = settings
        self.vectors = vectors
        self.lexical = lexical
        self.ollama = ollama
        self.cache = EmbeddingCache(
            settings.embedding_cache_path, settings.embedding_cache_max_bytes
        )
        self.last_summary: IngestSummary | None = None

    def files(self, path: Path) -> list[Path]:
        return [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())

    def ingest(
        self,
        path: Path,
        corpus_sha: str = "",
        rebuild: bool = False,
        prune: bool = False,
        prune_confirmed: bool = False,
        reporter: Reporter | None = None,
        corpus_provenance: CorpusProvenance | None = None,
    ) -> tuple[int, int]:
        started = time.perf_counter()
        self.last_summary = None
        resolved_context = resolve_corpus_context(path)
        if resolved_context is not None:
            resolved_provenance = resolved_context.provenance
            if corpus_provenance is not None and corpus_provenance != resolved_provenance:
                raise ValueError("supplied corpus provenance does not match the ingest path")
            corpus_provenance = resolved_provenance
            corpus_sha = resolved_provenance.commit
        with ingest_lock(self.settings.ingest_lock_path):
            state_store = IndexStateStore(self.settings.index_state_path)
            state = state_store.validate(
                collection=self.settings.collection,
                embedding_provider="ollama",
                embedding_model=self.settings.embed_model,
                chunking_version=CHUNKING_VERSION,
                preprocessing_version=PREPROCESSING_VERSION,
                legacy_index=self._has_legacy_index(),
                rebuild=rebuild,
            )
            source_state_path = IndexStateStore.resolve_source_state_path(
                data_dir=self.settings.data_dir,
                state=state,
                legacy_path=self.settings.source_state_path,
            )
            records = {} if rebuild else SourceStateStore(source_state_path).load()
            files = self.files(path)
            self._emit(reporter, "discovery", discovered=len(files))
            changes = ChangePlanner.plan(files, records, path, corpus_sha=corpus_sha)
            work = [change for change in changes if change.status in {"new", "changed"}]
            missing = [change for change in changes if change.status == "missing"]
            skipped = sum(change.status == "unchanged" for change in changes)
            unsupported = sum(change.status == "unsupported" for change in changes)
            changed = sum(change.status == "changed" for change in changes)
            self._emit(
                reporter,
                "planning",
                changed=changed,
                skipped=skipped,
                missing=len(missing),
                unsupported=unsupported,
            )
            if prune and missing and not prune_confirmed:
                raise PruneConfirmationRequired([change.source for change in missing])
            if not rebuild and not work and not (prune_confirmed and missing):
                self._finish_summary(
                    reporter,
                    IngestSummary(
                        discovered=len(files),
                        changed=changed,
                        skipped=skipped,
                        missing=len(missing),
                        unsupported=unsupported,
                        active_generation=state.generation if state else None,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                    ),
                )
                return 0, 0

            old_chunks: list[Chunk] = []
            old_embeddings: list[list[float]] = []
            if not rebuild and self.vectors.has_data():
                old_chunks, old_embeddings = self.vectors.export()
            source_payload: dict[str, tuple[list[Chunk], list[list[float]]]] = {}
            for chunk, embedding in zip(old_chunks, old_embeddings, strict=True):
                chunks, embeddings = source_payload.setdefault(chunk.source, ([], []))
                chunks.append(chunk)
                embeddings.append(embedding)

            parsed: list[tuple[FileChange, list[Chunk]]] = []
            self._emit(reporter, "parsing", files=len(work))
            for change in work:
                parsed.append(
                    (
                        change,
                        parse_document(
                            change.path,
                            self.settings.chunk_size,
                            self.settings.chunk_overlap,
                            corpus_sha,
                        ),
                    )
                )

            new_chunks = [chunk for _, chunks in parsed for chunk in chunks]
            known_dimension = None if rebuild or state is None else state.embedding.dimension
            all_embeddings, cache_hits, cache_misses = self._embed_chunks(
                new_chunks, known_dimension, path, reporter
            )
            if all_embeddings and state is not None and not rebuild:
                dimension = len(all_embeddings[0])
                if state.embedding.dimension is not None and dimension != state.embedding.dimension:
                    raise IncompatibleIndexError(
                        "embedding dimension is incompatible; run "
                        "tracerag ingest PATH --rebuild"
                    )

            offset = 0
            updated_records = dict(records)
            for change, chunks in parsed:
                embeddings = all_embeddings[offset : offset + len(chunks)]
                offset += len(chunks)
                source_payload[change.source] = (chunks, embeddings)
                updated_records[change.source] = SourceRecord(
                    source=change.source,
                    relative_path=change.relative_path,
                    source_hash=change.source_hash,
                    corpus_sha=corpus_sha,
                    chunk_count=len(chunks),
                )
            if prune_confirmed:
                for change in missing:
                    source_payload.pop(change.source, None)
                    updated_records.pop(change.source, None)

            snapshot_chunks: list[Chunk] = []
            snapshot_embeddings: list[list[float]] = []
            for source in sorted(source_payload):
                chunks, embeddings = source_payload[source]
                ordered = sorted(zip(chunks, embeddings, strict=True), key=lambda item: item[0].chunk_id)
                snapshot_chunks.extend(chunk for chunk, _ in ordered)
                snapshot_embeddings.extend(embedding for _, embedding in ordered)
            dimension = (
                len(snapshot_embeddings[0])
                if snapshot_embeddings
                else (state.embedding.dimension if state is not None and not rebuild else None)
            )
            prepared = PreparedGeneration(
                chunks=tuple(snapshot_chunks),
                embeddings=tuple(tuple(vector) for vector in snapshot_embeddings),
                source_records=updated_records,
                embedding_provider="ollama",
                embedding_model=self.settings.embed_model,
                embedding_dimension=dimension,
                corpus_provenance=corpus_provenance,
            )
            self._emit(reporter, "staging", files=len(work), chunks=len(snapshot_chunks))
            outcome = GenerationTransaction(self.settings, state_store).execute(prepared, state)
            self._emit(reporter, "activation", generation=outcome.identity.generation)
            self._emit(
                reporter,
                "cleanup",
                generation=outcome.identity.generation,
                warnings=list(outcome.warnings),
            )
            self.vectors = VectorStore(self.settings.vector_path, outcome.identity.active_collection)
            self.lexical = BM25Store(self.settings.data_dir / outcome.identity.bm25_artifact)
            self._finish_summary(
                reporter,
                IngestSummary(
                    discovered=len(files),
                    indexed=len(work),
                    indexed_with_chunks=sum(bool(chunks) for _, chunks in parsed),
                    empty=sum(not chunks for _, chunks in parsed),
                    changed=changed,
                    skipped=skipped,
                    missing=len(missing),
                    pruned=len(missing) if prune_confirmed else 0,
                    unsupported=unsupported,
                    chunks_embedded=cache_misses,
                    cache_hits=cache_hits,
                    cache_misses=cache_misses,
                    active_generation=outcome.identity.generation,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                ),
            )
            return len(work), len(new_chunks)

    def _embed_chunks(
        self,
        chunks: list[Chunk],
        known_dimension: int | None,
        path: Path,
        reporter: Reporter | None = None,
    ) -> tuple[list[list[float]], int, int]:
        vectors: list[list[float] | None] = [None] * len(chunks)
        missing: list[int] = []
        cache_hits = 0
        for index, chunk in enumerate(chunks):
            cached = self.cache.get(
                chunk.content_hash,
                self.settings.embed_model,
                known_dimension,
                CHUNKING_VERSION,
                PREPROCESSING_VERSION,
            )
            if cached is None:
                missing.append(index)
                continue
            cache_hits += 1
            if known_dimension is not None and len(cached) != known_dimension:
                raise IncompatibleIndexError(
                    "cached embedding dimension is incompatible; run "
                    "tracerag ingest PATH --rebuild"
                )
            vectors[index] = cached

        cache_misses = len(missing)
        self._emit(
            reporter,
            "cache",
            chunks=len(chunks),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )
        self._emit(
            reporter,
            "embedding",
            chunks=len(chunks),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            batches=(cache_misses + self.settings.embed_batch_size - 1)
            // self.settings.embed_batch_size,
        )
        try:
            for start in range(0, len(missing), self.settings.embed_batch_size):
                batch_indexes = missing[start : start + self.settings.embed_batch_size]
                self._emit(
                    reporter,
                    "embedding_batch",
                    batch=(start // self.settings.embed_batch_size) + 1,
                    batches=(cache_misses + self.settings.embed_batch_size - 1)
                    // self.settings.embed_batch_size,
                    chunks=len(batch_indexes),
                )
                batch = [chunks[index] for index in batch_indexes]
                embedded = self.ollama.embed(
                    self.settings.embed_model,
                    [f"{chunk.heading_path}\n{chunk.text}" for chunk in batch],
                )
                for index, vector in zip(batch_indexes, embedded, strict=True):
                    if known_dimension is not None and len(vector) != known_dimension:
                        raise IncompatibleIndexError(
                            "embedding dimension is incompatible; run "
                            "tracerag ingest PATH --rebuild"
                        )
                    self.cache.put(
                        chunks[index].content_hash,
                        self.settings.embed_model,
                        len(vector),
                        CHUNKING_VERSION,
                        PREPROCESSING_VERSION,
                        vector,
                    )
                    vectors[index] = vector
        except OllamaError as exc:
            raise OllamaError(f"embedding {path}: {exc}") from exc
        return [cast(list[float], vector) for vector in vectors], cache_hits, cache_misses

    @staticmethod
    def _emit(reporter: Reporter | None, stage: str, **details: object) -> None:
        if reporter is None:
            return
        try:
            reporter(stage, details)
        except Exception:  # pragma: no cover - presentation must not corrupt ingest
            logger.warning("ingest reporter failed at stage %s", stage, exc_info=True)

    def _finish_summary(self, reporter: Reporter | None, summary: IngestSummary) -> None:
        self.last_summary = summary
        self._emit(reporter, "complete", **summary.as_dict())

    def _has_legacy_index(self) -> bool:
        has_vectors = getattr(self.vectors, "has_data", None)
        if callable(has_vectors):
            vector_data = bool(has_vectors())
        else:
            vector_data = bool(self.vectors.all_chunks())
        has_lexical = getattr(self.lexical, "has_data", None)
        if callable(has_lexical):
            lexical_data = bool(has_lexical())
        else:
            lexical_data = bool(getattr(self.lexical, "load", list)())
        return vector_data or lexical_data
