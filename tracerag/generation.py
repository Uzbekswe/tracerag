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
                raise CitationFormatError("The answer model omitted valid source citations")
        return answer, latency
