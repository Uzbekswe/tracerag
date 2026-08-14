# TraceRAG command reference

All commands run locally through `uv run tracerag`. Ollama must be running for
embedding, answering, evaluation, and benchmark commands; `doctor` reports the
models that are installed.

## Runtime and corpora

```bash
uv run tracerag doctor
uv run tracerag corpus fetch fastapi
uv run tracerag corpus fetch clippy
```

Each corpus profile is pinned to a commit and writes a manifest with its
allowlist, license, and discovered files. Ingest the printed allowlisted path:

```bash
uv run tracerag ingest data/corpus/fastapi/docs/en/docs
uv run tracerag ingest data/corpus/clippy/book/src/development
```

## Index lifecycle

```bash
uv run tracerag ingest PATH
uv run tracerag ingest PATH --rebuild
uv run tracerag ingest PATH --prune
uv run tracerag ingest PATH --prune --yes
uv run tracerag documents
uv run tracerag documents --verbose
uv run tracerag cache status
uv run tracerag cache clear --yes
```

Normal ingest is content-hash based and keeps missing files. `--prune` first
prints a deletion plan; only `--prune --yes` removes those sources. A schema,
model, or preprocessing mismatch prints the explicit `--rebuild` recovery
command. Rebuilds are staged and activated atomically. The active generation
owns its Chroma, BM25, source-state, and provenance artifacts; cleanup of an
older generation is best effort after activation. If an interrupted run leaves
stale artifacts, rerun `uv run tracerag ingest PATH --rebuild`; do not delete
the active index manifest by hand.

## Asking and evaluation

```bash
uv run tracerag ask "How do query parameters work?"
uv run tracerag ask "How do query parameters work?" --show-source 1
uv run tracerag ask "How do query parameters work?" --json
uv run tracerag ask "What is outside this corpus?" --show-nearest
uv run tracerag eval --dataset fastapi-v1
uv run tracerag eval --dataset clippy-v1 --limit 1
```

Answers include numbered evidence. `--show-nearest` is diagnostic only: a
question below the evidence threshold is refused and does not call the answer
model. Evaluation relevance uses exact relative source and heading targets,
not unstable chunk IDs.

## Measured benchmark

```bash
uv run tracerag benchmark --corpus fastapi --output-dir docs
```

The benchmark creates JSON and Markdown reports for clean ingest, unchanged
re-ingest, and a one-file edit. It records the local machine, model tags,
corpus pin, timings, cache behavior, and embedding calls. The no-change target
is an environment-specific observation on the M1 baseline, not a universal
performance guarantee.
