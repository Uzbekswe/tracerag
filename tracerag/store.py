from __future__ import annotations

import hashlib
import json
from pathlib import Path

import chromadb

from .models import Chunk
from .persistence import atomic_write_json


class VectorStore:
    def __init__(self, path: Path, collection: str) -> None:
        self.path = path
        self.collection_name = collection
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            collection, metadata={"hnsw:space": "cosine"}
        )

    def has_data(self) -> bool:
        return self.collection.count() > 0

    def reset(self) -> None:
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            self.collection_name, metadata={"hnsw:space": "cosine"}
        )

    def delete(self) -> None:
        self.client.delete_collection(self.collection_name)

    def export(self) -> tuple[list[Chunk], list[list[float]]]:
        result = self.collection.get(
            include=["documents", "metadatas", "embeddings"]
        )
        chunks: list[Chunk] = []
        embeddings: list[list[float]] = []
        raw_embeddings = result.get("embeddings")
        if raw_embeddings is None:
            raw_embeddings = []
        for index, (chunk_id, text, metadata) in enumerate(
            zip(
                result.get("ids", []),
                result.get("documents", []),
                result.get("metadatas", []),
                strict=False,
            )
        ):
            metadata = metadata or {}
            chunks.append(
                Chunk(
                    chunk_id=str(chunk_id),
                    text=str(text),
                    source=str(metadata.get("source", "")),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    heading_path=str(metadata.get("heading_path", "")),
                    content_hash=str(metadata.get("content_hash", "")),
                    corpus_sha=str(metadata.get("corpus_sha", "")),
                    chunk_type=str(metadata.get("chunk_type", "text")),
                    source_hash=str(metadata.get("source_hash", "")),
                )
            )
            embeddings.append([float(value) for value in raw_embeddings[index]])
        return chunks, embeddings

    def import_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError("chunk and embedding counts must match")
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=embeddings,
            metadatas=[chunk.metadata() for chunk in chunks],
        )

    def replace_source(
        self, source: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None:
        existing = self.collection.get(where={"source": source}, include=[])
        ids = existing.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        if chunks:
            self.collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                documents=[chunk.text for chunk in chunks],
                embeddings=embeddings,
                metadatas=[chunk.metadata() for chunk in chunks],
            )

    def all_chunks(self) -> list[Chunk]:
        result = self.collection.get(include=["documents", "metadatas"])
        chunks: list[Chunk] = []
        for chunk_id, text, metadata in zip(
            result.get("ids", []),
            result.get("documents", []),
            result.get("metadatas", []),
            strict=False,
        ):
            metadata = metadata or {}
            chunks.append(
                Chunk(
                    chunk_id=str(chunk_id),
                    text=str(text),
                    source=str(metadata.get("source", "")),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    heading_path=str(metadata.get("heading_path", "")),
                    content_hash=str(metadata.get("content_hash", "")),
                    corpus_sha=str(metadata.get("corpus_sha", "")),
                    chunk_type=str(metadata.get("chunk_type", "text")),
                    source_hash=str(metadata.get("source_hash", "")),
                )
            )
        return chunks

    def query(self, embedding: list[float], top_k: int) -> list[tuple[Chunk, float]]:
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[tuple[Chunk, float]] = []
        for text, metadata, distance in zip(
            result.get("documents", [[]])[0],
            result.get("metadatas", [[]])[0],
            result.get("distances", [[]])[0],
            strict=False,
        ):
            metadata = metadata or {}
            chunk = Chunk(
                chunk_id=str(metadata.get("chunk_id", ""))
                or self._fallback_id(
                    str(metadata.get("source", "")), int(metadata.get("chunk_index", 0))
                ),
                text=str(text),
                source=str(metadata.get("source", "")),
                chunk_index=int(metadata.get("chunk_index", 0)),
                heading_path=str(metadata.get("heading_path", "")),
                content_hash=str(metadata.get("content_hash", "")),
                corpus_sha=str(metadata.get("corpus_sha", "")),
                chunk_type=str(metadata.get("chunk_type", "text")),
                source_hash=str(metadata.get("source_hash", "")),
            )
            hits.append((chunk, 1.0 / (1.0 + float(distance))))
        return hits

    @staticmethod
    def _fallback_id(source: str, index: int) -> str:
        return f"{source}:{index}"

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
                    "status": "current"
                    if current_hash and current_hash == stored_hash
                    else ("changed" if current_hash else "missing"),
                }
            )
        return result


class BM25Store:
    """A small persisted lexical index rebuilt from Chroma's authoritative chunks."""

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
