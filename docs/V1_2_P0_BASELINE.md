# TraceRAG v1.2 P0 Baseline Record

## Scope

This record freezes the audited v1.1 baseline and captures deterministic
reproductions for the two correctness findings assigned to P1. It does not
implement either fix and does not invoke Ollama or run model-backed evaluation.

Recorded: 2026-08-14 (Asia/Seoul)

## Git and GitHub references

| Item | Value |
| --- | --- |
| Working branch | `codex/v1.2-hardening` |
| Branch base | `8f156be042a631e24a8160ff4b93e82f5a7cce13` |
| Base subject | `Merge release gate documentation` |
| Preserved tag | `v1.1.0` |
| Preserved tag commit | `a4ab028522587ed2bb9084d25a16fbf4336849f8` |
| Remote | `https://github.com/Uzbekswe/tracerag.git` |
| Repository visibility | private |
| Default branch | `main` |
| Main CI run | https://github.com/Uzbekswe/tracerag/actions/runs/31805603829 |
| Main CI head | `8f156be042a631e24a8160ff4b93e82f5a7cce13` |
| Main CI result | successful: Ruff, deterministic tests, package build |

The v1.1 tag was not moved or rewritten. No branch was pushed and no GitHub
setting was changed during P0.

## Local environment

| Item | Value |
| --- | --- |
| Machine | Apple MacBook Air, arm64 |
| OS | macOS 26.5.2 |
| Host Python | 3.14.3 (not used by the project commands) |
| Project Python | 3.13.2 (`.venv/bin/python3`) |
| uv | 0.11.15 |
| Git | 2.50.1 |

The project environment was already locked and usable. No Ollama request was
made, and no generation or embedding model was changed.

## Baseline commands

These commands were run from the branch base before adding the P0 reproduction
tests:

```text
uv run pytest -q                 -> 77 passed in 1.49s
uv run ruff check .              -> All checks passed
uv lock --check                  -> Resolved 89 packages
uv build                         -> tracerag-1.1.0 sdist and wheel built
```

The successful main CI run performed the same lock validation, Ruff, deterministic
tests, and package-build checks remotely.

## P0 reproduction tests

Two strict `xfail` tests were added. They are intentionally failing regression
tests for P1, not fixes:

1. `test_documents_incompatible_index_prints_rebuild_guidance` creates an
   incompatible index-state manifest and asserts the desired CLI behavior: no
   traceback and the exact `tracerag ingest PATH --rebuild` instruction. The
   current implementation fails before the CLI error boundary.
2. `test_initial_all_empty_corpus_persists_authoritative_empty_source_state`
   ingests one empty Markdown file using a fake embedding client and asserts an
   active generation plus an `empty` source record. The current implementation
   discards the initial stage when no embedding dimension exists.

Focused reproduction command:

```text
uv run pytest \
  tests/test_cli.py::test_documents_incompatible_index_prints_rebuild_guidance \
  tests/test_staging.py::test_initial_all_empty_corpus_persists_authoritative_empty_source_state -q
-> 2 xfailed
```

The tests use temporary directories and fake embeddings only. They do not
contact Ollama.

## Tracked-file and runtime-data check

The repository tracks no files under `data/`, `reports/`, `dist/`, or `.venv/`,
and no tracked database, pickle, model, cache, binary, or executable artifact.
The existing ignore rules cover local data, reports, build output, virtualenvs,
and Python caches. Local runtime data remains outside the Git tree.

## Remaining P0/P1 boundary

P0 freezes and reproduces the baseline. P1 must implement the two failing
regressions. The Chroma advisory, transaction redesign, supply-chain changes,
GitHub security settings, pushes, tags, and repository visibility remain out of
scope for P0.
