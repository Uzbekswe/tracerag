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
            source_store = SourceStateStore(source_state_path)
            records = {} if rebuild else source_store.load()
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

            staged = self._supports_generations()
            old_collection = getattr(self.vectors, "collection_name", None)
            old_bm25_path = getattr(self.lexical, "path", self.settings.bm25_path)
            stage_vectors = self.vectors
            stage_lexical = self.lexical
            generation = IndexStateStore.new_generation()
            stage_collection = self._stage_collection_name(generation)
            stage_bm25_path = self.settings.bm25_generations_path / f"{generation}.json"
            activated = False
            prepared: PreparedGeneration | None = None
            transaction = GenerationTransaction(self.settings, state_store)
            active_generation = state.generation if state is not None else None
            if staged:
                stage_vectors = VectorStore(self.settings.chroma_path, stage_collection)
                stage_lexical = BM25Store(stage_bm25_path)
                self._emit(
                    reporter,
                    "staging",
                    generation=generation,
                    collection=stage_collection,
                )

            try:
                if staged and not rebuild and self.vectors.has_data():
                    chunks, embeddings = self.vectors.export()
                    stage_vectors.import_chunks(chunks, embeddings)

                if rebuild and not staged:
                    self._reset_index()

                parsed: list[tuple[FileChange, list[Chunk]]] = []
                self._emit(reporter, "parsing", files=len(work))
                for change in work:
                    chunks = parse_document(
                        change.path,
                        self.settings.chunk_size,
                        self.settings.chunk_overlap,
                        corpus_sha,
                    )
                    parsed.append((change, chunks))

                all_chunks = [chunk for _, chunks in parsed for chunk in chunks]
                known_dimension = (
                    None if rebuild or state is None else state.embedding.dimension
                )
                all_embeddings, cache_hits, cache_misses = self._embed_chunks(
                    all_chunks, known_dimension, path, reporter
                )

                if all_embeddings and state is not None and not rebuild:
                    dimension = len(all_embeddings[0])
                    if dimension != state.embedding.dimension:
                        raise IncompatibleIndexError(
                            "embedding dimension is incompatible; run "
                            "tracerag ingest PATH --rebuild"
                        )

                offset = 0
                updated_records = dict(records)
                for change, chunks in parsed:
                    embeddings = all_embeddings[offset : offset + len(chunks)]
                    offset += len(chunks)
                    stage_vectors.replace_source(change.source, chunks, embeddings)
                    updated_records[change.source] = SourceRecord(
                        source=change.source,
                        relative_path=change.relative_path,
                        source_hash=change.source_hash,
                        corpus_sha=corpus_sha,
                        chunk_count=len(chunks),
                    )
                if prune_confirmed:
                    for change in missing:
                        stage_vectors.replace_source(change.source, [], [])
                        updated_records.pop(change.source, None)

                staged_chunks = stage_vectors.all_chunks()
                if work or (prune_confirmed and missing):
                    stage_lexical.save(staged_chunks)

                if staged:
                    dimension = (
                        state.embedding.dimension
                        if state is not None and not rebuild
                        else (len(all_embeddings[0]) if all_embeddings else None)
                    )
                    if dimension is None:
                        self._discard_stage(stage_vectors, stage_lexical)
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
                                active_generation=active_generation,
                                elapsed_ms=(time.perf_counter() - started) * 1000,
                            ),
                        )
                        return len(work), len(all_chunks)
                    prepared = transaction.prepare(
                        generation=generation,
                        collection_name=stage_collection,
                        bm25_path=stage_bm25_path,
                        source_records=updated_records,
                        embedding_provider="ollama",
                        embedding_model=self.settings.embed_model,
                        embedding_dimension=dimension,
                        corpus_provenance=corpus_provenance,
                    )
                    transaction.activate(prepared)
                    active_generation = prepared.identity.generation
                    activated = True
                    self._emit(reporter, "activation", generation=prepared.identity.generation)
                    self._cleanup_previous_generation(
                        old_collection,
                        old_bm25_path,
                        source_state_path,
                        stage_collection,
                        stage_bm25_path,
                        prepared.source_state_path,
                    )
                    self._emit(reporter, "cleanup", generation=prepared.identity.generation)
                else:
                    if work or (prune_confirmed and missing):
                        self.lexical.save(self.vectors.all_chunks())
                        source_store.save(updated_records)

                if not staged and all_embeddings:
                    identity = IndexStateStore.new(
                        collection=self.settings.collection,
                        embedding_provider="ollama",
                        embedding_model=self.settings.embed_model,
                        embedding_dimension=len(all_embeddings[0]),
                    )
                    state_store.save(identity)
                    active_generation = identity.generation
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
                        active_generation=active_generation,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                    ),
                )
                return len(work), len(all_chunks)
            except BaseException:
                if staged and not activated:
                    self._discard_stage(stage_vectors, stage_lexical)
                    transaction.discard(prepared)
                raise

    def _supports_generations(self) -> bool:
        return all(
            hasattr(self.vectors, name)
            for name in ("export", "import_chunks", "delete")
        )

    def _stage_collection_name(self, generation: str) -> str:
        suffix = f"__{generation[:16]}"
        return f"{self.settings.collection[: 63 - len(suffix)]}{suffix}"

    @staticmethod
    def _discard_stage(stage_vectors, stage_lexical) -> None:
        try:
            if hasattr(stage_vectors, "delete"):
                stage_vectors.delete()
        finally:
            if hasattr(stage_lexical, "clear"):
                stage_lexical.clear()

    def _cleanup_previous_generation(
        self,
        old_collection: str | None,
        old_bm25_path: Path,
        old_source_state_path: Path,
        new_collection: str,
        new_bm25_path: Path,
        new_source_state_path: Path,
    ) -> None:
        if old_collection and old_collection != new_collection and hasattr(self.vectors, "delete"):
            try:
                self.vectors.delete()
            except Exception:  # pragma: no cover - cleanup is best effort after activation
                logger.warning("could not clean previous Chroma generation", exc_info=True)
        if old_bm25_path != new_bm25_path:
            try:
                old_bm25_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - cleanup is best effort after activation
                logger.warning("could not clean previous BM25 generation", exc_info=True)
        if old_source_state_path != new_source_state_path:
            try:
                old_source_state_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - cleanup is best effort after activation
                logger.warning("could not clean previous source state", exc_info=True)

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

    def _reset_index(self) -> None:
        reset = getattr(self.vectors, "reset", None)
        if callable(reset):
            reset()
        clear = getattr(self.lexical, "clear", None)
        if callable(clear):
            clear()
