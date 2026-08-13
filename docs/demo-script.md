# TraceRAG v1 terminal demo

Run this from a clean checkout after installing the two Ollama models. Keep the
terminal recording under three minutes and show the commands and their output.

```bash
uv sync --locked --extra dev
uv run tracerag doctor
uv run tracerag corpus fetch fastapi
uv run tracerag ingest data/corpus/fastapi/docs/en/docs
uv run tracerag documents
uv run tracerag ask "How do query parameters work?"
uv run tracerag ask "How do query parameters work?" --show-source 1 --json
uv run tracerag ask "What is the capital of France?" --show-nearest
uv run tracerag eval
```

The recording should make four behaviors visible: local setup checks, evidence
retrieval, numbered citations with source expansion, and refusal of a question
outside the indexed corpus. The evaluation command is the final quality gate;
do not describe the project as passing until its generated report meets the
thresholds in `PLAN.md`.
