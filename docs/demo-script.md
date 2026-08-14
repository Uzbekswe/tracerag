# TraceRAG v1.1 terminal demo

Run this from a clean checkout after installing the two Ollama models. The
benchmark is intentionally a longer measurement; record it separately from the
short interactive walkthrough.

```bash
uv sync --locked --extra dev
uv run tracerag doctor
uv run tracerag corpus fetch fastapi
uv run tracerag ingest data/corpus/fastapi/docs/en/docs
uv run tracerag documents
uv run tracerag ask "How do query parameters work?"
uv run tracerag ask "How do query parameters work?" --show-source 1 --json
uv run tracerag ask "What is the capital of France?" --show-nearest
uv run tracerag eval --dataset fastapi-v1 --limit 1
uv run tracerag benchmark --corpus fastapi --output-dir docs
uv run tracerag corpus fetch clippy
uv run tracerag ingest data/corpus/clippy/book/src/development
uv run tracerag eval --dataset clippy-v1 --limit 1
```

The short recording should make five behaviors visible: local setup checks,
evidence retrieval, numbered citations with source expansion, refusal of a
question outside the indexed corpus, and a no-change ingest summary. The
benchmark and full evaluations are release evidence; the captured H5 reports
meet the thresholds in `V1_1_PLAN.md`.
