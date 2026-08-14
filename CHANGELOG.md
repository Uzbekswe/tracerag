# Changelog

## [1.2.0] - 2026-08-15

TraceRAG v1.2 reduces public-release risk while preserving the local,
citation-first terminal workflow.

- Replaced the Chroma runtime dependency with a SQLite-backed exact vector
  store, removing the affected server code from the dependency tree.
- Added pinned container and CI inputs, non-root execution, bounded container
  write paths, Dependabot configuration, and a focused CodeQL workflow.
- Added the security policy, local trust boundary, reproducibility instructions,
  evaluation methodology, and explicit LocalRAG attribution and corpus licenses.
- Added typed document statuses, a single ingest-summary conversion seam, and a
  pure evaluation scoring seam without changing the retrieval contract.

## [1.1.0] - 2026-08-14

TraceRAG v1.1 hardens the original local, citation-first terminal workflow for
repeatable use on a compact machine.

- Added a versioned index contract, exclusive ingest lock, staged activation,
  and explicit rebuild recovery.
- Added content-hash incremental planning and an exact, bounded embedding cache.
- Preserved the last known-good index across failed updates and made pruning an
  explicit, confirmed operation.
- Added bounded Rich ingest progress and compact or verbose document summaries.
- Added the pinned Rust Clippy engineering-guide corpus alongside FastAPI.
- Upgraded evaluation to exact relative-source and heading targets with
  machine-readable provenance and visible release-gate failures.
- Added a citation-preserving extractive fallback when a local generation model
  exhausts its answer budget before emitting a valid citation.
- Added the three-phase benchmark, captured FastAPI evidence, deterministic CI,
  command reference, limitations, and release documentation.
- The 2026-08-14 hardening capture passes the local evidence gates: FastAPI
  reached 100% citation validity, 100% Recall@5, and 97.1% deterministic
  factuality; Clippy reached 100% for all three metrics. See `docs/evidence/`
  for the complete reports and per-case diagnostics.

TraceRAG is an independent implementation informed by the public architecture
of [n0nuser/LocalRAG](https://github.com/n0nuser/LocalRAG); see the README for
full attribution and corpus licenses.
