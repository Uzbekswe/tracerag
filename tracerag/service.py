from __future__ import annotations

import re
import time
from pathlib import Path

from .config import Settings
from .generation import CitationFormatError, Generator
from .index_state import IndexStateStore
from .models import AnswerResult, SearchHit
from .ollama import OllamaClient
from .retrieval import Retriever
from .source_state import SourceStateStore
from .store import BM25Store, VectorStore


class RAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.ollama = OllamaClient(self.settings.ollama_url, self.settings.request_timeout)
        active_collection, active_bm25 = IndexStateStore.resolve_active_storage(
            data_dir=self.settings.data_dir,
            state_path=self.settings.index_state_path,
            default_collection=self.settings.collection,
            default_bm25_path=self.settings.bm25_path,
        )
        self.vectors = VectorStore(self.settings.vector_path, active_collection)
        self.lexical = BM25Store(active_bm25)
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
        vector_documents = self.vectors.documents()
        try:
            state = IndexStateStore(self.settings.index_state_path).load()
            source_state_path = IndexStateStore.resolve_source_state_path(
                data_dir=self.settings.data_dir,
                state=state,
                legacy_path=self.settings.source_state_path,
            )
        except (OSError, ValueError):
            return vector_documents
        if not source_state_path.exists():
            return vector_documents
        records = SourceStateStore(source_state_path).load()
        if not records:
            return vector_documents
        documents: list[dict[str, object]] = []
        for source, record in sorted(records.items()):
            path = Path(source)
            if not path.is_file():
                status = "missing"
            else:
                try:
                    current_hash = SourceStateStore.hash_file(path)
                except OSError:
                    current_hash = ""
                status = "changed" if current_hash != record.source_hash else "current"
                if status == "current" and record.chunk_count == 0:
                    status = "empty"
            documents.append(
                {
                    "source": source,
                    "chunks": record.chunk_count,
                    "content_hash": record.source_hash,
                    "source_hash": record.source_hash,
                    "relative_path": record.relative_path,
                    "status": status,
                }
            )
        return documents
