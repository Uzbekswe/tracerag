# TraceRAG release gates

This page is the compact, public view of the checks used for a release. The
historical implementation plans remain local engineering notes; this document
records the externally meaningful contract.

## Deterministic gate

From a clean checkout with Python 3.13 and `uv`:

```bash
uv sync --locked --extra dev
uv lock --check
uv run ruff check .
uv run pytest -q
uv build
```

The CI workflow also audits the locked runtime dependency export with
`pip-audit` and checks medium/high Bandit findings. It does not download Ollama
models or private documents.

## Retrieval and answer gate

The versioned FastAPI and Clippy datasets are evaluated against pinned public
corpora. A release target is:

- 100% citation validity;
- at least 90% exact source-plus-heading Recall@5; and
- at least 85% manually reviewed factuality.

Deterministic expected-fact matching is a diagnostic proxy, not a replacement
for semantic review. Refusal behavior, no-change re-ingestion, source expansion,
and recovery messages are checked separately. The sanitized per-case evidence
is under [`docs/evidence/`](evidence/), with the current procedure and results
in [evaluation-report-v1.2.md](evaluation-report-v1.2.md).

## Security boundary

TraceRAG is a single-user local CLI. It uses an embedded SQLite vector store,
does not start a database listener, keeps Ollama on loopback in the optional
Compose path, and treats documents and model responses as untrusted input.
See [`SECURITY.md`](../SECURITY.md) for the reporting policy and limitations.
