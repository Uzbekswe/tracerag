from __future__ import annotations

import re
import time

from .config import Settings
from .generation import CitationFormatError, Generator
from .models import AnswerResult, SearchHit
from .ollama import OllamaClient
from .retrieval import Retriever
from .store import BM25Store, VectorStore


class RAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.ollama = OllamaClient(self.settings.ollama_url, self.settings.request_timeout)
        self.vectors = VectorStore(self.settings.chroma_path, self.settings.collection)
        self.lexical = BM25Store(self.settings.bm25_path)
        self.retriever = Retriever(
            self.vectors, self.lexical, self.ollama, self.settings.embed_model, self.settings.top_k
        )
        self.generator = Generator(
            self.ollama,
            self.settings.generation_model,
            self.settings.max_answer_tokens,
            self.settings.model_context,
        )

    def retrieve(self, question: str, top_k: int | None = None) -> list[SearchHit]:
        return self.retriever.retrieve(question, top_k)

    def ask(
        self,
        question: str,
        show_nearest: bool = False,
        hits: list[SearchHit] | None = None,
    ) -> AnswerResult:
        started = time.perf_counter()
        hits = hits if hits is not None else self.retrieve(question)
        best_evidence_score = max(
            (max(hit.dense_score, hit.lexical_score) for hit in hits),
            default=0.0,
        )
        if (
            not hits
            or best_evidence_score < self.settings.min_retrieval_score
            or not self._question_supported(question, hits)
        ):
            nearest = hits if show_nearest else []
            return AnswerResult(
                question,
                "",
                nearest,
                True,
                "No retrieved passage met the evidence threshold.",
                self.settings.generation_model,
                self.settings.embed_model,
                self.settings.min_retrieval_score,
                self.settings.top_k,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        try:
            answer, generation_ms = self.generator.answer(question, hits)
        except CitationFormatError as exc:
            return AnswerResult(
                question,
                "",
                hits,
                True,
                str(exc),
                self.settings.generation_model,
                self.settings.embed_model,
                self.settings.min_retrieval_score,
                self.settings.top_k,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        return AnswerResult(
            question,
            answer,
            hits,
            False,
            None,
            self.settings.generation_model,
            self.settings.embed_model,
            self.settings.min_retrieval_score,
            self.settings.top_k,
            latency_ms=generation_ms,
        )

    @staticmethod
    def _question_supported(question: str, hits: list[SearchHit]) -> bool:
        """Require enough question-specific vocabulary in retrieved evidence."""
        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "by",
            "can",
            "do",
            "does",
            "for",
            "from",
            "get",
            "how",
            "i",
            "in",
            "is",
            "it",
            "of",
            "on",
            "or",
            "the",
            "their",
            "this",
            "to",
            "use",
            "used",
            "what",
            "when",
            "where",
            "which",
            "who",
            "with",
            "work",
            "works",
            "fastapi",
            "configured",
            "settings",
            "declared",
            "handled",
            "components",
        }
        terms = [
            term for term in re.findall(r"[a-z0-9]+", question.lower()) if term not in stop_words
        ]
        if not terms:
            return True
        evidence = " ".join(hit.chunk.text.lower() for hit in hits)
        matched = sum(term in evidence or term.rstrip("s") in evidence for term in terms)
        return matched / len(terms) >= 0.5

    def documents(self) -> list[dict[str, object]]:
        return self.vectors.documents()
