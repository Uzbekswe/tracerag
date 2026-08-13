from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    source: str
    chunk_index: int
    heading_path: str
    content_hash: str
    corpus_sha: str = ""
    chunk_type: str = "text"
    source_hash: str = ""

    def metadata(self) -> dict[str, str | int]:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "chunk_index": self.chunk_index,
            "heading_path": self.heading_path,
            "content_hash": self.content_hash,
            "corpus_sha": self.corpus_sha,
            "chunk_type": self.chunk_type,
            "source_hash": self.source_hash,
        }


@dataclass
class SearchHit:
    chunk: Chunk
    score: float
    dense_score: float = 0.0
    lexical_score: float = 0.0


@dataclass
class AnswerResult:
    question: str
    answer: str
    sources: list[SearchHit] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None
    model: str = ""
    embedding_model: str = ""
    retrieval_threshold: float = 0.0
    top_k: int = 0
    provider: str = "ollama"
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "answer": self.answer,
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "model": self.model,
            "embedding_model": self.embedding_model,
            "retrieval_threshold": self.retrieval_threshold,
            "top_k": self.top_k,
            "provider": self.provider,
            "latency_ms": round(self.latency_ms, 2),
            "sources": [
                {
                    "citation": i,
                    "source": hit.chunk.source,
                    "chunk_index": hit.chunk.chunk_index,
                    "heading_path": hit.chunk.heading_path,
                    "content_hash": hit.chunk.content_hash,
                    "corpus_sha": hit.chunk.corpus_sha,
                    "chunk_type": hit.chunk.chunk_type,
                    "source_hash": hit.chunk.source_hash,
                    "score": round(hit.score, 6),
                    "preview": hit.chunk.text[:300],
                }
                for i, hit in enumerate(self.sources, start=1)
            ],
        }
