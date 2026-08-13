# TraceRAG FastAPI v1 evaluation

This is the checked-in release snapshot produced by the full default-timeout
run of `uv run tracerag eval --dataset fastapi-v1 --baseline evals/baseline/fastapi-v1.json`
on 2026-08-14.

| Metric | Result | Gate |
|---|---:|:---:|
| Citation validity (35 in-scope cases) | 100.0% | PASS |
| Retrieval recall@5 (35 in-scope cases) | 100.0% | PASS |
| Deterministic factuality check (35 in-scope cases) | 100.0% | PASS |
| Out-of-scope refusal accuracy (5 cases) | 100.0% | diagnostic |

Reproduction metadata:

- Corpus: FastAPI commit `f336ff831c4af3d4f625c2593a27b1e0cae93eb7`
- Indexed path: `data/corpus/fastapi/docs/en/docs`
- Embeddings: Ollama `nomic-embed-text`
- Generation: Ollama `qwen3:4b`
- Retrieval: Chroma cosine search + BM25 + weighted reciprocal-rank fusion
- Evidence threshold: `0.72`

The deterministic factuality number is supplemented by a separate semantic
review of all 35 in-scope answers in [`manual-review.md`](manual-review.md).
The full per-case JSON/Markdown output is generated under `reports/` and
intentionally ignored from source control because it contains local absolute
paths and timings. The checked-in baseline remains a regression reference, not
a universal quality guarantee for other corpora or models.
