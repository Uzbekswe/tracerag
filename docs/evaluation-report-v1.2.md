# TraceRAG v1.2 evaluation evidence

This record captures the single clean post-backend P7 run on 2026-08-15. Both
corpora were copied to a fresh temporary data directory before rebuild; no v1.1
index, cache, report, or generated answer was reused. Runtime settings stayed
at `nomic-embed-text`, `qwen3:4b`, context 2048, and answer budget 96.

## Results

| Corpus | Cases | Citation validity | Recall@5 | Deterministic factuality | Semantic review | Refusal accuracy |
|---|---:|---:|---:|---:|---:|---:|
| FastAPI | 40 (35 in-scope) | 100.0% | 100.0% | 100.0% | 35/35 (100.0%) | 100.0% |
| Clippy | 15 (12 in-scope) | 100.0% | 100.0% | 83.3% | 12/12 (100.0%) | 100.0% |

The Clippy deterministic proxy misses c01 and c11 because the answers use
supported wording without the literal expected-fact tokens `source code` and
`duties`. The semantic review records both as factually supported; c01 is
explicitly less complete because it gives the source-install command but not
the separate repository-clone step. This limitation remains visible in the
JSON report rather than being rewritten away.

The machine-readable reports are [FastAPI](evidence/fastapi-v1.2.json) and
[Clippy](evidence/clippy-v1.2.json), with reviewer-readable Markdown beside
each report. The companion reviews are
[FastAPI](manual-review-fastapi-v1.2.md) and
[Clippy](manual-review-clippy-v1.2.md).

## Comparison with v1.1

The v1.2 run preserves exact source-plus-heading Recall@5 and citation validity
for both corpora after replacing the vector backend. FastAPI's deterministic
factuality improved from the v1.1 proxy miss to 100.0%; Clippy's semantic result
remains 100.0%, while its deterministic proxy exposes the two wording
limitations above. The earlier v1.1 reports remain unchanged as historical
baseline evidence.
