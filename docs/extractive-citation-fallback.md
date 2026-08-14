# Extractive citation fallback

TraceRAG keeps a small deterministic fallback for local generation failures.
The generator first asks the configured Ollama model for a citation-formatted
answer, retries once with a larger token budget when the response is malformed,
and then selects up to two short, question-relevant sentences directly from the
retrieved passages. Each selected sentence receives the citation number of its
supplied passage.

This is an intentional release behavior: it preserves a useful, verifiable
answer when a small local model omits citations. It is extractive rather than a
general reasoning capability, is capped at 70 words, and never adds evidence
outside the retrieved passages. If no valid citation can be produced, the
service refuses instead of returning an uncited answer. The contract is covered
by `tests/test_generation.py`.
