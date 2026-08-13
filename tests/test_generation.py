from tracerag.generation import build_prompt, validate_citations
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
