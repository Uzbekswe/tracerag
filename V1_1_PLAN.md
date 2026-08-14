# TraceRAG v1.1 — Reliable Local Indexing and Evidence Plan

## Status

**M1, M2, M3, M4, M5, M6, and M7 complete.**

This is the source of truth for v1.1. An implementation agent must complete
exactly one milestone at a time, run that milestone's acceptance checks, update
this file's status, and stop for review before beginning the next milestone.

## Release intent

TraceRAG v1.1 makes the existing citation-first CLI trustworthy to operate on a
compact Apple Silicon laptop. It adopts selected mature  patterns—content
identity, embedding reuse, exclusive ingestion ownership, and safe replacement—
without turning TraceRAG into an API, agent, or platform project.

The default local baseline remains:

- Hardware: Apple M1 MacBook Air, 8 GB unified memory.
- Embeddings: Ollama `nomic-embed-text`.
- Generation: Ollama `qwen3:4b`.
- Retrieval: current Chroma + BM25 reciprocal-rank fusion.

CPU continues to parse, hash, and run BM25/Chroma. Ollama performs local model
inference. v1.1 must reduce unnecessary embedding work; it must not require
larger models, hosted inference, Docker, or GPU-specific application code.

## Product contracts

1. **No-change ingest is cheap.** File content hashes, not modification times,
   determine whether parsing, chunking, embedding, and index work is necessary.
2. **Cache entries are exact.** A chunk vector may be reused only when its text
   hash, embedding model, embedding dimension, and preprocessing/chunking
   version match.
3. **Updates are safe.** One process owns writes to an index. An ingest writes a
   staged index and only atomically activates it after every required operation
   succeeds. A failed ingest leaves the active index untouched.
4. **Deletion requires intent.** Missing documents remain indexed by default.
   `--prune` presents a deletion plan; deletion occurs only with `--yes`.
5. **Formats fail clearly.** A changed index schema, retrieval identity, or
   incompatible embedding space must print a clear recovery command:
   `tracerag ingest PATH --rebuild`.
6. **Evidence is stable.** Evaluation relevance is based on a relative source
   path plus heading path, never a chunk ID. A case can name multiple acceptable
   evidence targets; one target in the top five is a retrieval hit.
7. **Normal CLI output is compact.** Rich progress shows stages and totals; the
   document listing is a summary by default and detailed only with `--verbose`.
8. **v1 remains compatible.** Existing v1 commands and defaults continue to
   work. v1.1 adds flags, profiles, and richer output rather than breaking paths.

## Public corpus profiles

| Profile | Pinned source | Allowed corpus path | Purpose |
| --- | --- | --- | --- |
| `fastapi` | Existing FastAPI pin | `docs/en/docs` | Reproducible technical documentation benchmark |
| `clippy` | [`rust-lang/rust-clippy`](https://github.com/rust-lang/rust-clippy) at `d2c4d1532d89488a56ec2c3ca12757117fc0b4e2` | `book/src/development/**` | Public engineering guide: tooling, tests, lint authoring, release/process questions |

The Clippy profile must verify its allowlist and record its URL, immutable commit,
license (`MIT OR Apache-2.0`), fetch time, and discovered file count in a corpus
manifest. It must not ingest the rest of the Rust Clippy repository.

## Target command surface

```text
tracerag corpus fetch fastapi
tracerag corpus fetch clippy

tracerag ingest PATH [--collection NAME] [--prune] [--yes] [--rebuild]
tracerag documents [--collection NAME] [--verbose]
tracerag cache status
tracerag cache clear --yes

tracerag ask QUESTION [--show-source N] [--show-nearest] [--json]
tracerag eval [--dataset fastapi-v1|clippy-v1] [--baseline PATH] [--limit N]
tracerag benchmark --corpus fastapi
```

`--rebuild` is intentionally attached to `ingest`: the target path stays visible
and no separate index-management subsystem is introduced. `cache clear` is a
local cache operation only; it never removes indexed documents.

## Milestones

### M1 — Versioned index contract and exclusive write ownership

**Goal:** Establish the persistent contracts that prevent incompatible or
concurrent changes from silently corrupting a collection.

**Build**

- Add a versioned index-state manifest under the data directory. It records the
  active collection generation, schema version, collection name, embedding
  identity (provider/model/dimension), and chunking/preprocessing identity.
- Add typed errors for an incompatible index and a concurrent ingest. Show the
  exact `tracerag ingest PATH --rebuild` recovery command for incompatibility.
- Add a process-level advisory lock around the ingest write boundary. A second
  writer fails fast; queries remain unlocked.
- Add `--rebuild` plumbing. It authorizes replacement of incompatible index
  state; it is never triggered silently.
- Preserve all v1 command behavior when no version manifest exists: detect the
  legacy index, explain the one-time rebuild, and do not guess its compatibility.

**Acceptance checks**

- A second ingest against the same data directory fails clearly and writes no
  documents.
- A changed embedding or chunking identity fails before embedding begins and
  prints the rebuild command.
- `--rebuild` is the only path that replaces an incompatible index.
- Tests cover lock contention, manifest compatibility, legacy-index detection,
  and rebuild authorization without requiring Ollama.

**Status:** `complete`

### M2 — Incremental change planning and exact embedding cache

**Goal:** Determine precisely what changed before calling Ollama, then reuse
vectors safely whenever content is identical.

**Build**

- Persist source-level state: absolute source identity, source content hash,
  indexed relative path/provenance, and chunk count.
- Add a change planner that classifies candidates as `new`, `changed`,
  `unchanged`, `missing`, or `unsupported` before parsing/embedding.
- Skip parse, chunk, Ollama embedding, and Chroma writes for `unchanged` files.
- Add a bounded, on-disk LRU embedding cache (default 512 MB). Cache keys must
  include text hash and the full identity contract from the product contracts.
- Add `tracerag cache status` and `tracerag cache clear --yes`.
- Cache corruption or an unreadable cache is fail-open: re-embed affected chunks,
  report the event, and never invalidate the active index.

**Acceptance checks**

- An unchanged re-ingest makes zero embed calls and reports every file skipped.
- Changing one source touches only that source; identical chunks reuse cached
  vectors when valid.
- Changing model/dimension/preprocessing identity produces cache misses.
- LRU eviction, status, and confirmed clear are deterministic in unit tests.
- No full local model is needed for test coverage; mock the Ollama embedding
  client and assert its calls.

**Status:** `complete`

### M3 — Staged atomic activation and document lifecycle

**Goal:** Make incremental ingest safe even if parsing, embedding, disk I/O, or
the process fails during an update.

**Build**

- Build each update in a generated staging collection and matching versioned
  BM25 artifact. Do not mutate the active generation in place.
- Atomically replace the small active-index manifest only after stage validation
  and BM25 persistence succeed. Remove failed stages; preserve the last
  known-good active generation.
- Retain the previous generation until the new one is active; clean it only after
  successful activation according to a documented, recoverable cleanup policy.
- Implement missing-file handling. Normal ingest reports missing indexed files
  but retains them. `--prune` prints a precise plan; `--prune --yes` removes only
  the named missing sources in the staged replacement.
- Ensure the active generation selects both Chroma and BM25 consistently when a
  new `RAGService` starts.

**Acceptance checks**

- An injected parse/embed/write failure leaves query results from the old index
  available and byte-for-byte unchanged.
- Successful ingest activates Chroma and BM25 from the same generation.
- `--prune` alone deletes nothing; `--prune --yes` removes only missing sources.
- Tests cover failure preservation, activation, no-prune behavior, and confirmed
  pruning using temporary local storage.

**Status:** `complete`

### M4 — Operator-friendly terminal experience

**Goal:** Make long local operations understandable without flooding the user.

**Build**

- Add Rich stage progress for discovery, change planning, parsing/chunking,
  cache reuse, embedding batches, index staging, activation, and cleanup.
- Show elapsed time and a final summary: discovered, indexed, changed, skipped,
  missing, pruned, chunks embedded, cache hits/misses, and active index version.
- Change `tracerag documents` to a concise summary (source count, chunk count,
  current/changed/missing counts, active format/version). Move per-source rows to
  `tracerag documents --verbose`.
- Keep machine-readable paths available through existing JSON-oriented flows; do
  not bury errors inside Rich progress output.

**Acceptance checks**

- Normal FastAPI ingest produces bounded terminal output regardless of file count.
- The final summary distinguishes a no-change run from a full re-index.
- `documents --verbose` retains source-level diagnosis; default `documents` does
  not emit hundreds of rows.
- CLI tests snapshot meaningful summaries, errors, and exit codes.

**Status:** `complete`

### M5 — Reproducible Clippy demonstration corpus

**Goal:** Add a second public profile that tests engineering-process questions
without mixing private data into the repository.

**Build**

- Generalize corpus profile definitions without breaking `corpus fetch fastapi`.
- Implement `tracerag corpus fetch clippy` with the pinned Rust Clippy commit and
  `book/src/development/**` allowlist.
- Verify expected files exist after checkout; write a manifest beside the corpus
  and preserve corpus-specific provenance through ingest and evaluation.
- Update `doctor`, help text, README, and corpus tests for both profiles.

**Acceptance checks**

- Each fetch prints its exact commit and writes an auditable manifest.
- Clippy fetch rejects an unexpected/missing allowlisted tree rather than
  silently ingesting the repository root.
- Tests validate each profile's pin, license metadata, and allowed path behavior
  without network access.

**Status:** `complete`

### M6 — Exact-source evaluation and trustworthy reports

**Goal:** Make retrieval claims meaningful rather than treating any file beneath
`docs` as a successful retrieval.

**Build**

- Upgrade every FastAPI evaluation record to use one or more accepted evidence
  targets: normalized relative source path plus normalized heading path.
- Add 10–15 manually authored Clippy cases, including in-scope questions and
  explicit out-of-scope refusal checks.
- Replace broad substring relevance checks with exact target matching at top five.
- Retain the existing citation, refusal, expected-fact, baseline-comparison, and
  non-zero release-gate behavior.
- Extend JSON and Markdown reports with dataset/corpus pins, index schema,
  retrieval targets, matched target (if any), cache/index provenance, and failure
  classification.

**Acceptance checks**

- A retrieved wrong file or wrong heading cannot pass Recall@5.
- Any accepted target in the top five passes; chunk IDs are absent from the
  evaluation truth contract.
- Dataset validation rejects malformed targets and missing required fields.
- Fast tests cover exact matching, multiple acceptable targets, refusal cases,
  report rendering, and baseline regression.

**Status:** `complete`

### M7 — Measured release evidence, CI, and v1.1.0 handoff

**Goal:** Publish an honest, reproducible portfolio release rather than an
unmeasured feature list.

**Build**

- Add `tracerag benchmark --corpus fastapi` that writes a machine-readable JSON
  result and a readable Markdown report for: clean ingest, unchanged re-ingest,
  and one-file edit re-ingest. Record hardware, OS, Python, TraceRAG revision,
  Ollama/model tags, corpus pin, file/chunk counts, elapsed time, and embedding
  call counts.
- On the target M1 baseline, demonstrate no-change ingest in 10 seconds or less
  with zero embedding calls. If an environment-specific result differs, report
  it precisely; do not claim a universal speed guarantee.
- Add GitHub Actions for lock validation, Ruff, and deterministic unit tests.
  Do not run Ollama, evaluations, or hardware benchmarks in cloud CI.
- Update README, architecture documentation, command reference, limitations,
   attribution, and an explicit v1.1 changelog.
- Run both corpus demos, source expansion, refusal behavior, exact-source eval,
  benchmark, and capture a terminal recording.
- Create a `v1.1.0` Git tag only after all acceptance checks pass. The repository
  remains private unless its owner later chooses otherwise.

**Acceptance checks**

- `uv sync --locked --extra dev`, Ruff, and the deterministic test suite pass
  locally and in CI.
- Both corpus profiles reproduce from their pinned commits.
- Both evaluation reports meet their declared release gates and expose failures.
- The committed benchmark Markdown/JSON and terminal demo match the documented
  commands and current revision.
- Git history uses small, descriptive, professional commits; no fabricated task
  or milestone messages.

**Status:** `complete`

## Cross-milestone implementation rules

- Work only on the current milestone. Do not start a later milestone because a
  nearby change appears convenient.
- Start by writing or updating focused tests for the milestone's contracts, then
  implement the smallest design that satisfies them.
- Run `uv run ruff check .` and `uv run pytest` before declaring any milestone
  complete. Run command-level checks listed in that milestone as well.
- Preserve existing data until a staged replacement is proven valid. Do not use
  destructive Git commands or recursively delete broad directories.
- Keep optional Docker support compatible, but do not require a Docker daemon for
  correctness or developer workflow.
- Do not add a web UI, API, MCP server, agents, HyDE, rerankers, cloud providers,
  OCR, multi-user permissions, observability stacks, or Kubernetes in v1.1.
- If a milestone reveals an unplanned architectural decision, stop and update
  this plan before implementing around it.

## Completion checklist

- [x] M1 complete and reviewed
- [x] M2 complete and reviewed
- [x] M3 complete and reviewed
- [x] M4 complete and reviewed
- [x] M5 complete and reviewed
- [x] M6 complete and reviewed
- [x] M7 complete and reviewed
- [x] `v1.1.0` release evidence complete
