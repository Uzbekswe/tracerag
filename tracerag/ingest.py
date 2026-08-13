from __future__ import annotations

from pathlib import Path

from .config import Settings
from .models import Chunk
from .ollama import OllamaClient, OllamaError
from .parsers import parse_document
from .store import BM25Store, VectorStore


class Ingestor:
    def __init__(
        self, settings: Settings, vectors: VectorStore, lexical: BM25Store, ollama: OllamaClient
    ) -> None:
        self.settings = settings
        self.vectors = vectors
        self.lexical = lexical
        self.ollama = ollama

    def files(self, path: Path) -> list[Path]:
        candidates = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        return [p for p in candidates if p.suffix.lower() in {".md", ".markdown", ".txt", ".pdf"}]

    def ingest(self, path: Path, corpus_sha: str = "") -> tuple[int, int]:
        parsed: list[tuple[Path, list[Chunk]]] = []
        for file in self.files(path):
            chunks = parse_document(
                file, self.settings.chunk_size, self.settings.chunk_overlap, corpus_sha
            )
            parsed.append((file, chunks))

        all_chunks = [chunk for _, chunks in parsed for chunk in chunks]
        all_embeddings: list[list[float]] = []
        try:
            for start in range(0, len(all_chunks), self.settings.embed_batch_size):
                batch = all_chunks[start : start + self.settings.embed_batch_size]
                all_embeddings.extend(
                    self.ollama.embed(
                        self.settings.embed_model,
                        [f"{chunk.heading_path}\n{chunk.text}" for chunk in batch],
                    )
                )
        except OllamaError as exc:
            raise OllamaError(f"embedding {path}: {exc}") from exc

        offset = 0
        for file, chunks in parsed:
            embeddings = all_embeddings[offset : offset + len(chunks)]
            offset += len(chunks)
            self.vectors.replace_source(str(file.resolve()), chunks, embeddings)
        self.lexical.save(self.vectors.all_chunks())
        return len(parsed), len(all_chunks)
