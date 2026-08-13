from __future__ import annotations

import re
from collections import defaultdict

from rank_bm25 import BM25Okapi

from .models import Chunk, SearchHit
from .ollama import OllamaClient
from .store import BM25Store, VectorStore


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w.-]+", text.lower())


class Retriever:
    def __init__(
        self,
        vectors: VectorStore,
        lexical: BM25Store,
        ollama: OllamaClient,
        embed_model: str,
        top_k: int = 5,
    ) -> None:
        self.vectors = vectors
        self.lexical = lexical
        self.ollama = ollama
        self.embed_model = embed_model
        self.top_k = top_k

    def retrieve(self, question: str, top_k: int | None = None) -> list[SearchHit]:
        limit = top_k or self.top_k
        vector_hits = self.vectors.query(
            self.ollama.embed(self.embed_model, [question])[0], max(limit * 3, 10)
        )
        chunks = self.lexical.load() or self.vectors.all_chunks()
        lexical_hits: list[tuple[Chunk, float]] = []
        if chunks:
            index = BM25Okapi([_tokens(chunk.text) for chunk in chunks])
            scores = index.get_scores(_tokens(question))
            order = sorted(range(len(chunks)), key=lambda i: float(scores[i]), reverse=True)[
                : max(limit * 3, 10)
            ]
            lexical_hits = [(chunks[i], float(scores[i])) for i in order]
        combined: dict[str, SearchHit] = {}
        rank_scores: defaultdict[str, float] = defaultdict(float)
        for rank, (chunk, score) in enumerate(vector_hits, 1):
            combined[chunk.chunk_id] = SearchHit(chunk, 1.0 / (60 + rank), dense_score=score)
            rank_scores[chunk.chunk_id] += 0.55 / (60 + rank)
        max_lexical = max((score for _, score in lexical_hits), default=0.0) or 1.0
        for rank, (chunk, score) in enumerate(lexical_hits, 1):
            if chunk.chunk_id not in combined:
                combined[chunk.chunk_id] = SearchHit(chunk, 0.0)
            combined[chunk.chunk_id].lexical_score = score / max_lexical
            rank_scores[chunk.chunk_id] += 0.45 / (60 + rank)
        for chunk_id, hit in combined.items():
            hit.score = rank_scores[chunk_id]
        ranked = sorted(
            combined.values(),
            key=lambda hit: (hit.score, hit.dense_score, hit.chunk.chunk_id),
            reverse=True,
        )
        # Heading-only Markdown fragments are useful breadcrumbs but poor
        # evidence. Prefer substantive chunks when enough candidates exist;
        # retain short-only results for refusal diagnostics.
        substantive = [hit for hit in ranked if len(hit.chunk.text.strip()) >= 80]
        return (substantive if len(substantive) >= limit else ranked)[:limit]
