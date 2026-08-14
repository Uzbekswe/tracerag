# TraceRAG v1.1 — Release Hardening Plan

## Status

**H1, H2, H3, H4, H5, and H6 are complete.**

This plan is the source of truth for correcting the pre-push findings discovered
after the original v1.1 milestones were implemented. Complete exactly one
milestone at a time. For each milestone:

1. Write or update the focused tests first.
2. Implement only that milestone.
3. Run its command-level acceptance checks, Ruff, and the deterministic suite.
4. Update only that milestone's status in this file.
5. Stop for review before starting the next milestone.

Do not push a branch, open a pull request, delete or recreate the release tag,
or rewrite Git history before H6.

## Release decision

The current local implementation is substantial, but it is not yet an honest
`v1.1.0` release. The pre-push audit found two correctness blockers:

- a source-state write failure can occur after the active index manifest has
  already switched to the new generation;
- corpus fetch uses a per-corpus manifest but ingest and evaluation can read an
  unrelated global manifest, allowing incorrect corpus provenance.

The local `v1.1.0` tag therefore represents a release candidate only. It must
not be pushed. H6 removes and recreates it only after the corrected branch has
passed GitHub CI.

H3's initial sanitized FastAPI and Clippy evidence scaffolds have now been
replaced by complete H5 reports and semantic-review records. H5's full local
release gates passed before H6; H6 completed the history, CI, and remote-release
work that made the v1.1 release reviewable.

## Preserved product boundaries

The v1.1 product remains a local-first, citation-first terminal application.
This hardening work must not add a web UI, HTTP API, MCP server, agent loop,
hosted inference, OCR, authentication, multi-user infrastructure, rerankers,
HyDE, Kubernetes, or a Docker requirement.

The default baseline remains:

- Apple M1 MacBook Air with 8 GB unified memory;
- Python 3.13;
- Ollama `nomic-embed-text` embeddings;
- Ollama `qwen3:4b` generation;
- Chroma plus BM25 reciprocal-rank fusion;
- native `uv` workflow, with Docker optional.

## Corrected architecture

The active index manifest must be the only activation pointer. A generation is
not eligible for activation until all of its required artifacts are durable and
validated:

```text
discovery + corpus context
        |
        v
change plan -> parse -> cache/embed
        |
        v
staged generation
  - Chroma collection
  - BM25 artifact
  - source-state artifact
  - corpus provenance snapshot
        |
        v
validate complete generation
        |
        v
atomic manifest replacement  <-- only activation point
        |
        v
best-effort cleanup of the previous generation
```

Create one deep generation-transaction module with a small interface. Its
callers must not know artifact write ordering or rollback details. The interface
must expose the generation outcome and typed failure modes; tests exercise the
same interface as ingestion.

The index schema must be incremented because the active manifest gains a
generation-scoped source-state reference and a slot for generation provenance.
H1 owns atomic persistence of whatever provenance context its caller supplies;
H2 owns resolving and validating the correct context from an ingest path. An
existing pre-release v1.1 index must fail clearly with:

```text
tracerag ingest PATH --rebuild
```

The unversioned v1 legacy-index behavior remains explicit and compatible.

## Milestones

### H1 — Atomic generation transaction

**Goal:** Make “failed ingest leaves the active index untouched” true for every
required write, including source state.

**Build**

- Add a generation-scoped source-state artifact, for example
  `source-state/generations/<generation>.json`.
- Extend the versioned active manifest with the source-state artifact reference.
- Let the transaction persist an optional typed corpus-provenance value supplied
  by its caller, without deciding where that value comes from; path resolution
  belongs to H2.
- Increment the index schema and retain the explicit `--rebuild` recovery path
  for incompatible or legacy indexes.
- Introduce one generation-transaction module whose interface stages, validates,
  and activates a complete generation.
- Write Chroma, BM25, and source state before replacing the active manifest.
- Treat the manifest's atomic replacement as the only activation point.
- Remove failed staged artifacts when activation has not occurred.
- Keep cleanup after activation best-effort; cleanup failure must be reported but
  must not turn a successfully activated ingest into a failed transaction.
- Centralize atomic JSON persistence used by index state, source state, and the
  embedding cache where doing so reduces duplicated durability logic.
- Reduce `Ingestor.ingest` responsibility by moving artifact ordering,
  validation, activation, and rollback behind the transaction interface.

**Tests first**

- Inject failure during parsing, embedding, Chroma staging, BM25 persistence,
  source-state persistence, validation, and active-manifest replacement.
- For every pre-activation failure, assert that the active manifest bytes,
  active Chroma results, active BM25 bytes, and active source-state bytes remain
  unchanged.
- Assert that no failed stage becomes queryable and temporary artifacts are
  removed.
- Assert that a successful transaction activates matching Chroma, BM25, source
  state, and provenance from one generation.
- Assert that cleanup failure preserves the new active generation and produces
  an operator-visible warning.

**Acceptance checks**

- The previously reproduced source-state failure no longer changes queryable
  content or the active manifest.
- `uv run pytest tests/test_staging.py tests/test_index_contract.py -q` passes.
- `uv run ruff check .` passes.
- `uv run pytest -q` passes.

**Status:** `complete`

### H2 — Path-bound corpus provenance

**Goal:** Ensure the indexed and evaluated corpus identity always comes from the
actual input path, never from whichever profile was fetched most recently.

**Build**

- Resolve corpus context by walking from the ingest path to its nearest
  `.tracerag-corpus.json` ancestor.
- Validate the manifest schema, immutable commit, profile name, license, source
  URL, and allowed path before accepting it.
- Reject an ingest path that discovers a corpus manifest but escapes that
  profile's allowed tree.
- Allow arbitrary user documents without a corpus profile; record them as
  unprofiled instead of assigning unrelated provenance.
- Supply the resolved corpus context to the generation transaction and require
  it for profiled corpora; the transaction remains responsible for persisting it
  atomically.
- Stop using the global `data/manifest.json` as current corpus truth. Preserve a
  read-only legacy fallback only where required for existing v1 behavior; do not
  overwrite it on each new fetch.
- Make evaluation read provenance from the active generation.
- Before retrieval or model calls, reject a dataset whose corpus name or commit
  does not match the active generation. Give a precise fetch/ingest recovery
  command.
- Keep FastAPI and Clippy fetch destinations, pins, allowlists, and license
  metadata unchanged.

**Tests first**

- Fetch/profile fixtures for FastAPI and Clippy can coexist without overwriting
  one another's provenance.
- Fetching Clippy after FastAPI and then ingesting FastAPI still records the
  FastAPI commit.
- A path outside a profile's allowlist is rejected before parsing or embedding.
- An unprofiled personal path remains usable for ingest and ask.
- FastAPI evaluation against a Clippy generation, and the reverse, fails before
  retrieval or generation.
- Reports reproduce the active generation's exact corpus snapshot.

**Acceptance checks**

- `uv run pytest tests/test_corpus.py tests/test_evaluation.py -q` passes.
- Both profile manifests remain independently auditable.
- No test or runtime path treats the last-fetched profile as global truth.
- `uv run ruff check .` passes.
- `uv run pytest -q` passes.

**Status:** `complete`

### H3 — Durable, sanitized evaluation evidence

**Goal:** Preserve both full evaluation results in reviewer-safe files instead
of overwriting one `latest` report or relying on summary claims.

**Build**

- Give evaluation reports dataset-specific names, such as
  `reports/fastapi-v1.json` and `reports/clippy-v1.json`, with matching Markdown.
- Add an explicit output-directory option if needed for release capture while
  preserving the existing `tracerag eval` defaults.
- Store source paths relative to the validated corpus root in release reports.
  Do not commit usernames, home-directory paths, mutable collection paths, or
  other machine-local identifiers.
- Preserve per-case question, expected facts, accepted evidence targets, matched
  target and rank, answer, citations, failure classification, and release gates.
- Label deterministic expected-fact scoring honestly. Do not present it as a
  substitute for semantic human review.
- Add committed release snapshots under `docs/evidence/` for FastAPI and Clippy
  in JSON and Markdown.
- Split manual review into explicit FastAPI and Clippy documents. Review all 35
  FastAPI and all 12 Clippy in-scope answers against their cited passages.
- Keep refusal accuracy diagnostic unless the original release contract is
  explicitly amended.

**Tests first**

- Two sequential dataset runs produce separate reports without overwriting.
- Sanitization removes absolute workspace paths while retaining exact relative
  evidence identity.
- A failing case remains visible in JSON and Markdown and causes the declared
  non-zero exit.
- Report provenance must equal the active generation and dataset pin.
- Report rendering distinguishes deterministic checks from manual review.

**Acceptance checks**

- `uv run pytest tests/test_evaluation.py tests/test_cli.py -q` passes.
- Full report fixtures contain no absolute user paths.
- Both manual-review templates contain every in-scope case ID.
- `uv run ruff check .` passes.
- `uv run pytest -q` passes.

**Status:** `complete`

### H4 — Operator and reproducibility polish

**Goal:** Remove misleading release details and strengthen cheap automated
verification without expanding product scope.

**Build**

- Make generation source state the truth for `tracerag documents`, including
  zero-chunk sources that cannot appear in Chroma.
- Distinguish discovered files, indexed sources with chunks, and parsed-but-empty
  sources in ingest and document summaries.
- Show the FastAPI HTML-only `newsletter.md` case honestly instead of reporting
  both 155 and 154 as the same kind of source count.
- Preserve bounded normal output and source-level `--verbose` diagnosis.
- Pin GitHub Actions to the locally verified `uv 0.11.15` release.
- Add a package-build smoke check after lock validation, Ruff, and tests. Keep
  Ollama, full evaluations, and hardware benchmarks out of cloud CI.
- Update stale `v1` evidence headings to `v1.1` where they describe this release.
- Explain that the benchmark records the measured code revision and that a
  later evidence-only commit or merge commit cannot self-reference itself.
- Document the generation cleanup policy and operator recovery commands.

**Tests first**

- A zero-chunk Markdown document appears with an explicit empty status and does
  not inflate the count of indexed sources with chunks.
- Default document output stays bounded; verbose output includes the empty file.
- CI configuration pins uv and contains no Ollama/evaluation/benchmark step.
- Package metadata and runtime `__version__` remain `1.1.0`.

**Acceptance checks**

- `uv run pytest tests/test_cli.py tests/test_benchmark.py -q` passes.
- `uv build` succeeds from the locked environment.
- `uv run ruff check .` passes.
- `uv run pytest -q` passes.

**Status:** `complete`

### H5 — Reproduce and capture release evidence

**Goal:** Generate complete evidence from the corrected code on the target local
machine before any release tag is created.

**Procedure**

- Start from clean, isolated data directories so FastAPI and Clippy cannot share
  mutable state accidentally.
- Run `uv sync --locked --extra dev`, Ruff, all deterministic tests, and the
  package-build smoke check.
- Fetch both profiles and verify their exact pinned commits and manifests.
- Rebuild and run the full 40-case FastAPI evaluation with the documented local
  context and answer-token settings.
- Rebuild and run the full 15-case Clippy evaluation with the same documented
  settings.
- Preserve the four sanitized report files under `docs/evidence/`.
- Complete semantic citation review for 35 FastAPI and 12 Clippy in-scope
  answers; record disagreements rather than forcing a pass.
- Run the three-phase FastAPI benchmark from a clean benchmark directory.
- Record the measured code revision, dirty state, machine, OS, Python, model
  tags, corpus pin, file/chunk counts, elapsed time, cache behavior, and embedding
  calls.
- Capture one accurate terminal transcript covering doctor, both corpus fetches,
  ingest, no-change ingest, document summary, answer, expanded source, refusal,
  both evaluation summaries, and benchmark summary.
- Update README, changelog, evaluation documents, manual reviews, benchmark
  documents, and release checklist from the actual outputs only.

**Release gates**

- FastAPI and Clippy citation validity: 100%.
- FastAPI and Clippy Recall@5: at least 90%.
- Manual semantic factuality: at least 85% for each corpus.
- Full per-case reports expose every failure.
- No-change FastAPI ingest: zero embedding calls and at most 10 seconds on the
  recorded M1 machine; report any miss honestly rather than weakening the result.
- No release artifact contains an absolute user path or secret.

**Latest capture (2026-08-14):** The isolated FastAPI run reached 100% citation
validity, 100% Recall@5, and 97.1% deterministic factuality. Its only
deterministic expected-fact proxy miss (f16) is semantically supported and is
recorded in the manual review. The isolated Clippy run reached 100% citation
validity, 100% Recall@5, and 100% deterministic factuality. The FastAPI
benchmark passed the no-change gate at 0.072 seconds and zero embedding calls.
The complete reports, transcript, benchmark, and reviews are captured under
`docs/evidence/` and `docs/`.

**Acceptance checks**

- Every command in the terminal transcript can be matched to committed output.
- Both corpus pins in evaluation evidence match their active generation.
- Benchmark JSON and Markdown agree exactly on measured values.
- `git diff --check` passes.
- `uv run ruff check .` passes.
- `uv run pytest -q` passes.

**Status:** `complete`

### H6 — Professional history, GitHub CI, and final tag

**Goal:** Publish a reviewable private release branch, prove it in GitHub CI,
then create the release tag at the correct time.

**Safety and history procedure**

- Confirm the worktree is clean and `origin/main` still resolves to the expected
  fixed point before rewriting any unpushed history.
- Create a recoverable local safety branch, using the `codex/` prefix, that
  preserves the complete pre-rewrite tree and commits.
- Remove the stale local `v1.1.0` tag only after the safety branch is verified.
- Curate `origin/main..HEAD` into a coherent set of descriptive, professional
  commits. Do not create fake milestone, task-complete, AI, or noisy micro-commit
  messages; commit count is not a release criterion.
- Integrate the hardening corrections into the appropriate functional commits
  rather than hiding them in a vague “fixes” commit.
- Prefer this commit story, adjusting only when dependency order requires it:

  1. Establish index compatibility and exclusive writer ownership.
  2. Add content-based source change planning.
  3. Add the bounded exact embedding cache.
  4. Activate complete index generations atomically.
  5. Add safe pruning and operator summaries.
  6. Add reproducible FastAPI and Clippy profiles.
  7. Preserve path-bound corpus provenance.
  8. Enforce exact-source evaluation and durable reports.
  9. Add measured benchmarking and deterministic CI.
  10. Document and capture the v1.1 release evidence.

- Each commit must be internally coherent and should pass the relevant focused
  tests; the final history must pass the complete release checks.

**GitHub procedure**

- Push a `codex/v1.1-release` branch to the existing private repository.
- Open a pull request against `main` with the release contract, measured evidence,
  limitations, and exact local verification commands.
- Wait for GitHub Actions lock validation, Ruff, deterministic tests, and package
  build to succeed on the pull-request head.
- Review the final PR diff and CI result before merging.
- Merge without discarding the curated commit history.
- Confirm remote `main` contains the reviewed result and the repository remains
  private.
- Create a fresh annotated `v1.1.0` tag on the accepted remote-main commit only
  after CI succeeds, then push that tag.

**Acceptance checks**

- Local and remote histories contain the curated, descriptive v1.1 commit history;
  no arbitrary commit-count target is used.
- GitHub Actions is successful for the exact reviewed release commit.
- The pull request is merged and remote `main` contains the release tree.
- Remote `v1.1.0` resolves to the accepted `main` release commit.
- The repository remains private.
- No generated corpus, model, cache, local data, secret, absolute user path, or
  ignored runtime report was accidentally committed.
- `V1_1_PLAN.md` and this file accurately describe final release readiness.

**Status:** `complete`

## Final completion checklist

- [x] H1 atomic generation transaction complete and reviewed
- [x] H2 path-bound corpus provenance complete and reviewed
- [x] H3 durable sanitized evaluation evidence complete and reviewed
- [x] H4 operator and reproducibility polish complete and reviewed
- [x] H5 full local release evidence complete and reviewed
- [x] H6 curated history, GitHub CI, merge, and tag complete
- [x] Remote repository remains private
- [x] `v1.1.0` exists remotely only after successful CI

## Implementation handoff

An implementation model should begin with this instruction:

```text
Read V1_1_RELEASE_HARDENING_PLAN.md completely. Implement only H1: “Atomic
generation transaction.” Follow its build items and acceptance checks exactly.
Preserve all existing v1 behavior, write focused tests first, run Ruff and
pytest, update H1's status only when every acceptance check passes, then stop
and report changed files, commands run, evidence, and remaining risks. Do not
begin H2 and do not modify Git history, tags, branches, or remotes.
```
