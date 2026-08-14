from __future__ import annotations

import re

from .models import SearchHit
from .ollama import OllamaClient


class CitationFormatError(RuntimeError):
    """The generation model did not cite the supplied evidence correctly."""


def build_prompt(question: str, sources: list[SearchHit]) -> str:
    blocks = []
    for i, hit in enumerate(sources, 1):
        blocks.append(f"[{i}] {hit.chunk.source} | {hit.chunk.heading_path}\n{hit.chunk.text}")
    return (
        "You are a citation-first documentation assistant. Immediately write only the final "
        "answer using the evidence below; do not reason aloud, analyze sources, make a plan, or "
        "add a preamble. Keep it under 80 words. If unsupported, say it is not stated. Cite "
        "every factual sentence with source numbers like [1]. Do not invent citations.\n\n"
        f"QUESTION: {question}\n\nEVIDENCE:\n" + "\n\n".join(blocks)
    )


def validate_citations(answer: str, count: int) -> bool:
    citations = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
    return bool(citations) and all(1 <= citation <= count for citation in citations)


def _fallback_snippet(
    text: str, question_terms: set[str], max_words: int = 38
) -> str:
    """Return a short readable evidence excerpt for model-format failures."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    substantial = [sentence for sentence in sentences if len(sentence.split()) >= 3]
    snippet = max(
        substantial or [normalized],
        key=lambda sentence: sum(
            term in sentence.lower() for term in question_terms
        ),
    )
    words = snippet.split()
    if len(words) > max_words:
        snippet = " ".join(words[:max_words]).rstrip(".,;:") + "…"
    return snippet


def _extractive_fallback(question: str, sources: list[SearchHit]) -> str:
    """Build a citation-backed answer when the local model emits no valid answer."""
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "be",
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
        "to",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
    question_terms = {
        term for term in re.findall(r"[a-z0-9]+", question.lower()) if term not in stop_words
    }
    ranked: list[tuple[float, int, SearchHit]] = []
    for index, hit in enumerate(sources, start=1):
        heading = hit.chunk.heading_path.lower()
        evidence = hit.chunk.text.lower()
        heading_overlap = sum(term in heading for term in question_terms)
        text_overlap = sum(term in evidence for term in question_terms)
        relevance = heading_overlap * 4 + text_overlap * 2 + hit.lexical_score + hit.dense_score
        ranked.append((relevance, index, hit))
    ranked.sort(key=lambda item: (item[0], item[2].score), reverse=True)

    parts: list[str] = []
    word_count = 0
    for _, index, hit in ranked:
        snippet = _fallback_snippet(hit.chunk.text, question_terms)
        if not snippet:
            continue
        words = len(snippet.split()) + 1
        if parts and word_count + words > 70:
            continue
        parts.append(f"{snippet} [{index}]")
        word_count += words
        if len(parts) == 2:
            break
    return " ".join(parts)


class Generator:
    def __init__(
        self, ollama: OllamaClient, model: str, max_tokens: int, context_size: int = 2048
    ) -> None:
        self.ollama = ollama
        self.model = model
        self.max_tokens = max_tokens
        self.context_size = context_size

    def answer(self, question: str, sources: list[SearchHit]) -> tuple[str, float]:
        evidence = sources[:3]
        answer, latency = self.ollama.chat(
            self.model, build_prompt(question, evidence), self.max_tokens, self.context_size
        )
        if not validate_citations(answer, len(evidence)):
            retry_tokens = min(max(self.max_tokens * 2, 1200), 2048)
            answer, retry_latency = self.ollama.chat(
                self.model, build_prompt(question, evidence), retry_tokens, self.context_size
            )
            latency += retry_latency
            if not validate_citations(answer, len(evidence)):
                answer = _extractive_fallback(question, evidence)
                if not validate_citations(answer, len(evidence)):
                    raise CitationFormatError("The answer model omitted valid source citations")
        return answer, latency
