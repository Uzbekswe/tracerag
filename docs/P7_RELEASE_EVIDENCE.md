# v1.2 private release-candidate evidence

This record covers the P7 checks performed on 2026-08-15 before any visibility
change. The repository remains private and the v1.1 tag is unchanged.

## Deterministic checks

The following commands passed on the release branch:

```text
uv sync --locked --extra dev
uv lock --check
uv run ruff check .
uv run pytest -q                 # 95 passed
uv build                          # tracerag-1.2.0
git diff --check
uv export --locked --no-dev --no-emit-project --format requirements.txt
uv run pip-audit -r <exported requirements>
uv run bandit -q -r tracerag -ll
```

The tracked-file credential scan found no credential-pattern matches, and the
tracked-file artifact scan found no generated corpus, report, database, pickle,
binary, model, or cache file.

## Runtime and command checks

- The optional `linux/arm64` image built successfully and ran `--help` and
  `doctor` as UID 10001. Doctor correctly reported Ollama unavailable when no
  host service was provided.
- A clean Clippy re-ingest reused 339 cached embeddings; the following
  unchanged ingest completed in 0.01 seconds with zero embedding calls.
- `documents --verbose` exposed indexed source rows and statuses.
- An incompatible index manifest produced exit code 1, no traceback, and the
  exact recovery instruction `tracerag ingest PATH --rebuild`.

## Model-backed evidence

Because P3 replaced vector storage, one clean FastAPI and one clean Clippy run
were executed with the established local settings. The results and reviewer
decisions are recorded in [evaluation-report-v1.2.md](evaluation-report-v1.2.md).
FastAPI passed all three deterministic gates. Clippy passed citation validity
and Recall@5; its deterministic expected-fact proxy was 83.3%, while the
semantic review was 12/12 and records the two wording limitations explicitly.

No model-backed report was overwritten or relabeled as v1.1 evidence.
