# Contributing to TraceRAG

TraceRAG is a local-first terminal application. Contributions should preserve
the citation-first contract, deterministic reproduction path, and explicit
local-only trust boundary.

## Development setup

Use Python 3.13 and the committed lock file:

```bash
uv sync --locked --extra dev
uv run ruff check .
uv run pytest -q
uv lock --check
uv build
```

The deterministic checks do not need Ollama, model downloads, private
documents, or Docker. If a change affects parsing, retrieval, storage, or
answer generation, add a focused fixture or test and explain any changed
release evidence in the pull request.

## Scope

Keep the product local and command-oriented. Do not introduce a web UI, hosted
inference, a Chroma server, OCR, an agent loop, MCP, cloud storage, or
multi-user authorization without first opening a design discussion. Avoid
rewriting the storage or retrieval contract for style alone; changes should
reduce a measured risk or improve a tested behavior.

## Pull requests

1. Describe the user-visible behavior and the failure mode or evidence it
   addresses.
2. Include focused tests for behavior changes.
3. Report the exact local commands and results.
4. Do not commit local data, model files, generated reports, credentials, or
   machine-specific absolute paths.

Security issues should follow [`SECURITY.md`](SECURITY.md) rather than being
opened as public issues.
