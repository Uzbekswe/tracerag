from tracerag.generation import Generator, build_prompt, validate_citations
from tracerag.models import Chunk, SearchHit


def _hit() -> SearchHit:
    chunk = Chunk("id", "FastAPI is a framework.", "guide.md", 0, "Intro", "hash")
    return SearchHit(chunk, 0.1, dense_score=0.8)


def test_prompt_contains_numbered_evidence() -> None:
    prompt = build_prompt("What is FastAPI?", [_hit()])
    assert "[1] guide.md | Intro" in prompt
    assert "What is FastAPI?" in prompt


def test_citations_must_be_present_and_in_range() -> None:
    assert validate_citations("It is a framework [1].", 1)
    assert not validate_citations("It is a framework.", 1)
    assert not validate_citations("It is a framework [2].", 1)


class _EmptyOllama:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, *_args, **_kwargs) -> tuple[str, float]:
        self.calls += 1
        return "", 1.0


def test_generator_falls_back_to_cited_evidence_when_model_omits_answer() -> None:
    ollama = _EmptyOllama()
    generator = Generator(ollama, "qwen3:4b", max_tokens=96)

    answer, latency = generator.answer("What is FastAPI?", [_hit()])

    assert answer == "FastAPI is a framework. [1]"
    assert validate_citations(answer, 1)
    assert latency == 2.0
    assert ollama.calls == 2


def test_extractive_fallback_prefers_question_relevant_sentence() -> None:
    ollama = _EmptyOllama()
    generator = Generator(ollama, "qwen3:4b", max_tokens=96)
    hit = SearchHit(
        Chunk(
            "id",
            "Read the contributor overview first. This guide explains how to get the source code.",
            "guide.md",
            0,
            "Getting started",
            "hash",
        ),
        0.1,
        dense_score=0.8,
    )

    answer, _ = generator.answer("How do I get the source code?", [hit])

    assert "source code" in answer
    assert validate_citations(answer, 1)
