# TraceRAG benchmark

Benchmark: `tracerag-v1.1`
Corpus: `fastapi` @ `f336ff831c4af3d4f625c2593a27b1e0cae93eb7`
Allowed path: `docs/en/docs`

## Environment

- OS: `macOS-26.5.2-arm64-arm-64bit-Mach-O`
- Architecture: `arm64`
- CPUs: `8`
- Python: `3.13.2`
- TraceRAG revision: `c2c3ff19a540e92e46b7099dd867de58befef78f`
- Ollama tags: `qwen3:4b, nomic-embed-text:latest`

## Phases

| Phase | Files | Chunks | Elapsed | Embedding calls | Cache hits | Cache misses |
|---|---:|---:|---:|---:|---:|---:|
| clean_ingest | 155 | 2736 | 203.48s | 22 | 0 | 2736 |
| unchanged_reingest | 0 | 0 | 0.07s | 0 | 0 | 0 |
| one_file_edit_reingest | 1 | 24 | 10.57s | 1 | 23 | 1 |

## No-change assertion

- Result: **PASS**
- No-change elapsed: `0.072s` (target: <= 10s on the M1 baseline)
- No-change embedding calls: `0` (target: zero embedding calls)

The timing target is an environment-specific observation, not a universal guarantee.
