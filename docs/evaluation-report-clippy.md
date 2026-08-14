# TraceRAG Clippy evaluation

The Clippy profile evaluates a small public engineering-handbook corpus at the
pinned `rust-lang/rust-clippy` commit. It contains 12 in-scope questions and 3
out-of-scope refusal checks. Evidence truth uses exact normalized relative
source-plus-heading targets in the top five results.

## Reproduce

```bash
uv run tracerag corpus fetch clippy
uv run tracerag ingest data/corpus/clippy/book/src/development --rebuild
TRAGERAG_MODEL_CONTEXT=2048 TRAGERAG_MAX_ANSWER_TOKENS=96 \
  uv run tracerag eval --dataset clippy-v1
```

The generated JSON and Markdown reports include the corpus pin, index/cache
provenance, matched target and rank, per-case model output, and failure class.
The command exits non-zero when a release gate fails; no aggregate hides an
individual retrieval or refusal error.

## Captured H5 evidence (release gates passed)

On 2026-08-14, an isolated fetch and rebuild discovered 24 Markdown files and
indexed 339 chunks. The full 15-case run used the local `qwen3:4b` generator
with `TRAGERAG_MODEL_CONTEXT=2048` and `TRAGERAG_MAX_ANSWER_TOKENS=96` to keep
the evaluation practical on the 8 GB machine:

| Metric | Result | Gate |
|---|---:|:---:|
| Citation validity | 100.0% | PASS |
| Recall@5 | 100.0% | PASS |
| Deterministic factuality | 100.0% | PASS |
| Out-of-scope refusal accuracy | 100.0% | diagnostic |

The generated `reports/clippy-v1.json` and `reports/clippy-v1.md` reports also
record the index generation, cache provenance, matched target and rank,
latency, and any failure class. The complete captured report has no in-scope
refusal or citation failures.
