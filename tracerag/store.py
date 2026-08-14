from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
from pathlib import Path

from .models import Chunk
from .persistence import atomic_write_json
from .source_state import DocumentStatus

VECTOR_SCHEMA = "vectors-v1"


class VectorStore:
    """Persist vector chunks in one generation-scoped SQLite database."""

    def __init__(self, path: Path, collection: str) -> None:
        self.root = path
        self.collection_name = collection
        self.path = path / f"{collection}.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    source TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    heading_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    corpus_sha TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    embedding BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS vectors_source_idx ON vectors(source);
                CREATE TABLE IF NOT EXISTS vector_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO vector_metadata(key, value) VALUES ('generation', ?)",
                (self.collection_name,),
            )
            connection.execute(
                "INSERT OR IGNORE INTO vector_metadata(key, value) VALUES ('schema', ?)",
                (VECTOR_SCHEMA,),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _pack(vector: list[float]) -> bytes:
        if not vector or any(not math.isfinite(value) for value in vector):
            raise ValueError("embedding vector must contain finite values")
        return struct.pack(f"<{len(vector)}f", *vector)

    @staticmethod
    def _unpack(value: bytes, dimension: int) -> list[float]:
        return list(struct.unpack(f"<{dimension}f", value))

    @staticmethod
    def _validate_batch(chunks: list[Chunk], embeddings: list[list[float]]) -> int | None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunk and embedding counts must match")
        if not embeddings:
            return None
        dimensions = {len(vector) for vector in embeddings}
        if len(dimensions) != 1 or not next(iter(dimensions)):
            raise ValueError("embedding vectors must share one positive dimension")
        for vector in embeddings:
            VectorStore._pack(vector)
        return next(iter(dimensions))

    @staticmethod
    def _row_to_chunk(row: tuple[object, ...]) -> Chunk:
        return Chunk(
            chunk_id=str(row[0]),
            text=str(row[1]),
            source=str(row[2]),
            chunk_index=int(row[3]),
            heading_path=str(row[4]),
            content_hash=str(row[5]),
            corpus_sha=str(row[6]),
            chunk_type=str(row[7]),
            source_hash=str(row[8]),
        )

    @staticmethod
    def _row_to_embedding(row: tuple[object, ...]) -> list[float]:
        return VectorStore._unpack(bytes(row[10]), int(row[9]))

    @staticmethod
    def _insert_sql() -> str:
        return (
            "INSERT OR REPLACE INTO vectors "
            "(id, document, source, chunk_index, heading_path, content_hash, corpus_sha, "
            "chunk_type, source_hash, dimension, embedding) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )

    def _insert_rows(
        self,
        connection: sqlite3.Connection,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        dimension = self._validate_batch(chunks, embeddings)
        if dimension is None:
            return
        existing = connection.execute("SELECT MIN(dimension), MAX(dimension) FROM vectors").fetchone()
        if existing[0] is not None and (existing[0] != existing[1] or existing[0] != dimension):
            raise ValueError("embedding vectors must match the existing index dimension")
        connection.executemany(
            self._insert_sql(),
            [
                (
                    chunk.chunk_id,
                    chunk.text,
                    chunk.source,
                    chunk.chunk_index,
                    chunk.heading_path,
                    chunk.content_hash,
                    chunk.corpus_sha,
                    chunk.chunk_type,
                    chunk.source_hash,
                    dimension,
                    self._pack(vector),
                )
                for chunk, vector in zip(chunks, embeddings, strict=True)
            ],
        )

    def has_data(self) -> bool:
        connection = self._connect()
        try:
            return bool(connection.execute("SELECT 1 FROM vectors LIMIT 1").fetchone())
        finally:
            connection.close()

    def count(self) -> int:
        connection = self._connect()
        try:
            return int(connection.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])
        finally:
            connection.close()

    def reset(self) -> None:
        self.delete()
        self._initialize()

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_name(f"{self.path.name}-wal").unlink(missing_ok=True)
        self.path.with_name(f"{self.path.name}-shm").unlink(missing_ok=True)

    def export(self) -> tuple[list[Chunk], list[list[float]]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, document, source, chunk_index, heading_path, content_hash, "
                "corpus_sha, chunk_type, source_hash, dimension, embedding "
                "FROM vectors ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        return (
            [self._row_to_chunk(row) for row in rows],
            [self._row_to_embedding(row) for row in rows],
        )

    def import_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        connection = self._connect()
        try:
            self._insert_rows(connection, chunks, embeddings)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replace_source(
        self, source: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None:
        self._validate_batch(chunks, embeddings)
        connection = self._connect()
        try:
            connection.execute("DELETE FROM vectors WHERE source = ?", (source,))
            self._insert_rows(connection, chunks, embeddings)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def all_chunks(self) -> list[Chunk]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, document, source, chunk_index, heading_path, content_hash, "
                "corpus_sha, chunk_type, source_hash, dimension, embedding "
                "FROM vectors ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        return [self._row_to_chunk(row) for row in rows]

    def validate(
        self, expected_dimension: int | None, *, expected_collection: str | None = None
    ) -> None:
        if expected_collection is not None and self.collection_name != expected_collection:
            raise ValueError("vector generation collection does not match its index identity")
        connection = self._connect()
        try:
            metadata = dict(
                connection.execute("SELECT key, value FROM vector_metadata").fetchall()
            )
            if metadata.get("schema") != VECTOR_SCHEMA or metadata.get("generation") != self.collection_name:
                raise ValueError("vector generation metadata does not match its identity")
            count, minimum, maximum = connection.execute(
                "SELECT COUNT(*), MIN(dimension), MAX(dimension) FROM vectors"
            ).fetchone()
            if count == 0:
                return
            if minimum != maximum or expected_dimension != minimum:
                raise ValueError(
                    "vector generation dimension does not match its index identity"
                )
            row = connection.execute(
                "SELECT dimension, embedding FROM vectors ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None or not self.query(self._unpack(bytes(row[1]), int(row[0])), 1):
                raise ValueError("vector generation is not queryable")
        finally:
            connection.close()

    def query(self, embedding: list[float], top_k: int) -> list[tuple[Chunk, float]]:
        if top_k <= 0:
            return []
        query_dimension = len(embedding)
        if query_dimension == 0:
            raise ValueError("query embedding must not be empty")
        query_norm = math.sqrt(sum(value * value for value in embedding))
        if query_norm == 0:
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, document, source, chunk_index, heading_path, content_hash, "
                "corpus_sha, chunk_type, source_hash, dimension, embedding "
                "FROM vectors"
            ).fetchall()
        finally:
            connection.close()
        ranked: list[tuple[Chunk, float]] = []
        for row in rows:
            if int(row[9]) != query_dimension:
                raise ValueError("query embedding dimension does not match the index")
            vector = self._unpack(bytes(row[10]), int(row[9]))
            vector_norm = math.sqrt(sum(value * value for value in vector))
            cosine = (
                sum(left * right for left, right in zip(embedding, vector, strict=True))
                / (query_norm * vector_norm)
                if vector_norm
                else 0.0
            )
            score = 1.0 / (1.0 + (1.0 - cosine))
            ranked.append((self._row_to_chunk(row), score))
        ranked.sort(key=lambda item: (item[1], item[0].chunk_id), reverse=True)
        return ranked[:top_k]

    def documents(self) -> list[dict[str, object]]:
        chunks = self.all_chunks()
        grouped: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            grouped.setdefault(chunk.source, []).append(chunk)
        result: list[dict[str, object]] = []
        for source, items in sorted(grouped.items()):
            path = Path(source)
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
            stored_hash = items[0].source_hash
            result.append(
                {
                    "source": source,
                    "chunks": len(items),
                    "content_hash": items[0].content_hash,
                    "status": DocumentStatus.CURRENT
                    if current_hash and current_hash == stored_hash
                    else (
                        DocumentStatus.CHANGED
                        if current_hash
                        else DocumentStatus.MISSING
                    ),
                }
            )
        return result


class BM25Store:
    """A small persisted lexical index rebuilt from authoritative chunks."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, chunks: list[Chunk]) -> None:
        atomic_write_json(self.path, [chunk.__dict__ for chunk in chunks])

    def has_data(self) -> bool:
        if not self.path.exists():
            return False
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        return bool(value)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def load(self) -> list[Chunk]:
        if not self.path.exists():
            return []
        return [Chunk(**item) for item in json.loads(self.path.read_text(encoding="utf-8"))]

    def validate(self, expected_count: int) -> None:
        chunks = self.load()
        if len(chunks) != expected_count:
            raise ValueError("BM25 artifact count does not match the vector generation")
