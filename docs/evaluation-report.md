# TraceRAG FastAPI evaluation

This document describes the reproducible v1.1 evaluation rather than claiming
that one laptop run generalizes to every model or corpus. The dataset contains
40 records: 35 in-scope technical questions and 5 out-of-scope refusal checks.
In-scope relevance is an exact match of a normalized relative source path and
full heading path in the top five results; chunk IDs are not evaluation truth.

## Reproduce

```bash
uv run tracerag corpus fetch fastapi
uv run tracerag ingest data/corpus/fastapi/docs/en/docs --rebuild
TRAGERAG_MODEL_CONTEXT=2048 TRAGERAG_MAX_ANSWER_TOKENS=96 \
  uv run tracerag eval --dataset fastapi-v1
```

The command writes `reports/fastapi-v1.json` and `reports/fastapi-v1.md` only
after all requested cases finish. The JSON report records the pinned corpus, dataset,
index generation, models, cache, per-case matched target, latency, and failure
class. A non-zero exit means at least one declared release gate failed.

## Captured H5 evidence (release gates passed)

On 2026-08-14, after rebuilding the pinned FastAPI corpus on the target Apple
M1/8 GB machine, the latest full 40-case run used the local `qwen3:4b` generator with
`TRAGERAG_MODEL_CONTEXT=2048` and `TRAGERAG_MAX_ANSWER_TOKENS=96` to keep the
evaluation practical on this hardware:

| Metric | Result | Gate |
|---|---:|:---:|
| Citation validity | 100.0% | PASS |
| Recall@5 | 100.0% | PASS |
| Deterministic factuality | 97.1% | PASS |
| Out-of-scope refusal accuracy | 100.0% | diagnostic |

The benchmark artifact in [`benchmark-fastapi.md`](benchmark-fastapi.md) is the
release performance evidence: clean ingest, unchanged re-ingest, and one-file
edit re-ingest with model tags and embedding-call counts.

The complete report records no refusal or citation failures. f16 is
semantically supported but missed the literal `BackgroundTasks` expected-fact
token in the deterministic proxy; the distinction is recorded in the manual
review and does not fail the release gate.

## Release gates

The intended gates are 100% citation validity, at least 90% Recall@5 for
in-scope cases, and at least 85% factuality after the documented semantic
review. Out-of-scope refusal accuracy is reported separately. Failures remain
visible in the per-case report and must be investigated before a release tag.
