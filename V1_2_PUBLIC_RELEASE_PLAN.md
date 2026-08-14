# TraceRAG v1.2 — Public Release Hardening Plan

## Status

**Planning is complete. Implementation has not started and requires owner approval.**

This file is the source of truth for the audit-remediation and public-release
session that follows TraceRAG v1.1. Implement exactly one milestone at a time.
For every milestone:

1. Confirm the preceding milestone is complete.
2. Write or update focused tests first where behavior changes.
3. Implement only the current milestone.
4. Run its focused checks, Ruff, and the deterministic test suite.
5. Record the commands and evidence, update only that milestone's status, and
   stop for review.

Do not begin implementation, create the hardening branch, change GitHub
settings, push, merge, tag, or change repository visibility until the owner
explicitly approves the corresponding step.

## Objective

Turn the working private v1.1 repository into a defensible public portfolio
release by correcting the audit findings, reducing externally meaningful risk,
and preserving the project's local-first, citation-first design.

The work is ordered by risk:

1. correctness and failure safety;
2. vulnerable-dependency containment or removal;
3. supply-chain and container hardening;
4. focused maintainability improvements;
5. truthful portfolio documentation and public-release evidence.

The goal is not to minimize lines of code. Simplification is justified only
when it lowers security surface or maintenance cost without weakening tested
v1.1 behavior.

## Preserved product boundaries

- Local command-line application with Rich output.
- Python 3.13 and `uv` as the primary development workflow.
- Ollama `nomic-embed-text` embeddings and `qwen3:4b` generation remain the
  runtime baseline unless a separate benchmarked decision changes them.
- BM25 plus vector retrieval and citation-first answers remain product
  contracts.
- Docker remains optional.
- No web UI, HTTP service, Chroma server, hosted inference, agent loop, MCP
  server, OCR, authentication, multi-user layer, Kubernetes, or cloud database.
- Preserve the v1.1 tag and history. Do not rewrite or move `v1.1.0`.
- Use deterministic CPU-only tests during normal implementation. Run the full
  FastAPI and Clippy model-backed evaluations once at the final evidence stage
  only if retrieval, vector storage, embedding, or answer behavior changed.

## Verified starting point

The audit reviewed `24bb19e4726a2e3e5087f66700443882734ffc21` through
`6cbdca7` and verified the following private baseline:

- 77 deterministic tests pass.
- Ruff, package build, lock validation, and `git diff --check` pass.
- GitHub CI is successful for the current v1.1 branches, main, and tag.
- The repository is MIT-licensed and credits the MIT-licensed LocalRAG project.
- No tracked executable, database, pickle, symlink, secret, or malware indicator
  was found. This is not a formal malware certification.
- `chromadb==1.5.9` is affected by CVE-2026-45829 /
  GHSA-f4j7-r4q5-qw2c. TraceRAG currently uses only `PersistentClient`; it does
  not start or expose a Chroma server.
- Dependabot alerts, code scanning, and secret scanning are not enabled.

## Release blockers

Public visibility remains blocked until all of the following are resolved:

1. An initial all-empty corpus is persisted as authoritative source state.
2. `tracerag documents` converts an incompatible-index condition into a concise
   recovery message rather than a traceback.
3. One deep generation transaction owns all durable artifact staging,
   validation, activation, rollback, and cleanup.
4. Chroma/vector data is required during complete-generation validation.
5. Cleanup-failure behavior is tested and operator-visible.
6. The critical Chroma dependency has been removed/upgraded, or the owner has
   explicitly accepted a documented residual-risk exception after the measured
   replacement spike.
7. Mutable container and CI inputs, root-container execution, and GitHub
   security automation have been addressed.
8. Release documentation and evidence are internally accurate and contain no
   local paths, secrets, generated corpora, caches, or models.

## Target generation transaction

`Ingestor` should discover, parse, chunk, and obtain/reuse embeddings. It should
then pass one immutable prepared-generation value to a deep transaction module:

```text
Ingestor
  discover -> plan -> parse -> chunk -> embed/cache
                              |
                              v
                  PreparedGeneration
                              |
                              v
              GenerationTransaction.execute(...)
                  1. create staging generation
                  2. write vector data
                  3. write BM25 artifact
                  4. write source state
                  5. write identity + provenance
                  6. validate every staged artifact
                  7. atomically replace active manifest  <-- commit point
                  8. clean old generation, best effort
```

The caller must not know artifact ordering, collection naming, rollback steps,
or cleanup rules. Before the manifest replacement, any failure removes the
stage and leaves the active generation byte-for-byte and query-for-query
unchanged. After replacement, cleanup failure emits a warning but cannot undo
the successful activation.

The transaction interface should return a typed outcome and raise typed
pre-commit failures. Do not add a second transaction wrapper; deepen the
existing `GenerationTransaction` and delete superseded orchestration from
`Ingestor`.

## Milestones

### P0 — Freeze and reproduce the audited baseline

**Goal:** Start hardening from an exact, recoverable v1.1 state.

**Build**

- Confirm the worktree is clean and remote refs match the recorded v1.1 state.
- Create `codex/v1.2-hardening` from the accepted `main` commit, not from an
  unmerged side branch.
- Record the starting commit, tag target, Python/uv versions, lock state, and CI
  URLs in the implementation report.
- Reproduce the two correctness failures using temporary data and fake
  embeddings; do not invoke Ollama.
- Verify ignored `data/`, model files, caches, generated corpora, and local
  reports are not tracked.

**Acceptance checks**

- The new branch has an unambiguous base and `v1.1.0` is unchanged.
- The existing 77-test baseline, Ruff, build, lock check, and diff check pass.
- Both bugs have deterministic failing regression tests ready for P1.

**Status:** `complete`

### P1 — Correct user-visible compatibility and empty-source behavior

**Goal:** Fix the two concrete correctness failures without changing retrieval
or answer behavior.

**Build**

- Move `documents` index opening inside the CLI compatibility-error boundary.
- Translate `IndexCompatibilityError` and its subclasses into a concise error,
  non-zero exit, and exact `tracerag ingest PATH --rebuild` recovery command.
- Ensure an initial ingest containing only zero-chunk Markdown/PDF sources still
  persists a valid generation, source state, identity, and provenance.
- Report each zero-chunk source as `empty`; do not fabricate vector or BM25
  entries and do not inflate indexed-source or chunk counts.
- Preserve mixed empty/non-empty and no-change behavior.

**Tests first**

- Command-level incompatible-index test asserts no traceback and the exact
  recovery instruction.
- End-to-end all-empty initial-ingest test asserts an active generation exists
  and `documents --verbose` exposes the empty source.
- Mixed, repeated, rebuild, and unprofiled-source tests prevent regressions.

**Acceptance checks**

- Focused CLI, source-state, index-contract, and ingest tests pass.
- Ruff and the full deterministic suite pass without Ollama.
- No runtime model, retrieval threshold, or evidence file changes.

**Status:** `complete`

### P2 — Measure and decide the local vector backend

**Goal:** Choose the smallest defensible response to the critical Chroma
advisory before redesigning durable transaction ownership.

**Spike only**

- Define the actual vector-store contract used by TraceRAG: create a staged
  generation, add vectors and metadata, top-k similarity search, validate
  counts/dimensions/identity, open the active generation, and delete an obsolete
  generation.
- Compare the current embedded Chroma client with at least one smaller local
  candidate, preferring a SQLite-backed exact-search implementation suitable
  for the current corpus size over another server/platform dependency.
- Use deterministic fixed vectors and representative stored metadata. Measure
  install footprint, transitive dependencies, index size, stage/open/query
  latency, result ordering, failure behavior, portability, and maintenance
  burden.
- Confirm the candidate requires no network listener, unsafe remote model
  loading, or pickle deserialization.
- Do not change the production backend during the spike.

**Decision gate**

- Prefer replacement when the candidate satisfies the contract, deterministic
  result parity, acceptable local latency, and meaningfully reduces vulnerable
  or unnecessary dependencies.
- Otherwise retain embedded Chroma temporarily, enforce that only
  `PersistentClient` is constructible, document that running/exposing a Chroma
  server is unsupported, and stop before public release for explicit owner
  acceptance of the residual risk.
- Record the chosen direction and evidence in this file before P3 begins.

**Acceptance checks**

- The comparison is reproducible and CPU-only.
- No production behavior or dependency changed during the spike.
- The public-release implication of the decision is explicit.

**Decision (2026-08-14):** Replace Chroma in P3 with a SQLite-backed exact
local vector adapter. The deterministic 1,288-row, 768-dimensional spike
matched Chroma's exact top-k results for all four queries, used no new
dependency, and measured approximately 100 ms per query on the target machine.
The performance tradeoff and the requirement for final model-backed evaluation
after the storage change are recorded in
`docs/V1_2_P2_VECTOR_BACKEND_SPIKE.md`.

**Status:** `complete`

### P3 — Deep generation transaction and vector-backend mitigation

**Goal:** Make complete-generation activation a single deep, testable module
and implement the approved P2 backend decision.

**Build**

- Introduce a narrow vector-store adapter only if P2 proves a replacement or
  containment seam is necessary.
- Make `GenerationTransaction.execute(prepared_generation)` own creation and
  naming of staged artifacts, vector writes, BM25 persistence, source-state
  persistence, identity/provenance persistence, complete validation, atomic
  manifest replacement, rollback, and post-commit cleanup.
- Make vector count, dimension, generation identity, and queryability mandatory
  validation checks rather than an optional callback.
- Remove artifact-ordering, rollback, activation, and cleanup branches from
  `Ingestor`.
- Use typed transaction failures for stage, validation, activation, and cleanup
  reporting; do not expose backend-specific errors at the CLI boundary.
- If P2 selects replacement, remove Chroma imports and its dependency completely
  and regenerate the lock file. Do not leave dormant affected server code in
  the runtime environment.
- If P2 selects containment, add a regression test proving TraceRAG never starts
  or connects to a Chroma server and document the time-bounded exception.

**Tests first**

- Inject failure at every durable write and validation boundary.
- Assert every pre-commit failure preserves active manifest bytes, vector
  results, BM25 bytes, source-state bytes, identity, and provenance.
- Assert a successful transaction activates one matching generation across all
  artifacts.
- Inject obsolete-generation cleanup failure; assert activation remains
  successful and a user-visible warning identifies recoverable leftovers.
- Assert `Ingestor` uses only the transaction's public execution interface for
  durable generation changes.

**Acceptance checks**

- Transaction-focused, staging, index-contract, ingest, retrieval, and CLI tests
  pass.
- The earlier source-state failure and all newly injected failures cannot
  activate partial data.
- Ruff, the full deterministic suite, lock check, and package build pass.
- Dependency audit reflects the P2 decision accurately.

**Status:** `complete`

### P4 — Harden dependencies, containers, and CI inputs

**Goal:** Reduce mutable and unnecessarily privileged supply-chain surface.

**Build**

- Pin Python, uv, and Ollama container inputs to reviewed immutable digests while
  retaining readable version comments and a documented update procedure.
- Run the TraceRAG application container as a dedicated non-root user with only
  the data paths it needs writable.
- Keep Ollama bound to loopback in the optional host-facing configuration.
- Review whether `git` is required in the final TraceRAG runtime image; use a
  multi-stage build or documented tradeoff rather than keeping build tools by
  accident.
- Pin GitHub Actions to reviewed commit SHAs and retain version comments.
- Export the locked runtime dependency set and run a reproducible vulnerability
  audit. Store commands and summarized findings, not machine-local paths.
- Run Bandit at a documented severity threshold and classify justified
  subprocess use instead of suppressing findings globally.

**Tests and checks**

- Build the image and run `tracerag --help` and `tracerag doctor` as the non-root
  user without requiring model inference.
- Verify no Chroma or TraceRAG network listener is introduced.
- Verify compose still mounts documents read-only and persistent data only where
  intended.
- CI lock validation, Ruff, deterministic tests, security checks, and package
  build pass with least-privilege workflow permissions.

**Status:** `not started`

### P5 — Focused maintainability and contract cleanup

**Goal:** Remove proven complexity without performing a style-driven rewrite.

**Build**

- Replace repeated source/document status strings with one typed enum or other
  closed representation at the state/CLI seam.
- Centralize repeated `IngestSummary` construction behind one small builder or
  outcome conversion function.
- Remove obsolete staged/non-staged compatibility branches only after tests
  establish that no supported v1/v1.1 migration or rebuild flow requires them.
- Separate evaluation orchestration from scoring/report rendering only where it
  creates a deeper module with a smaller interface.
- Keep the extractive citation fallback provisionally. Document it as an
  intentional release behavior and add focused contract tests; remove it only
  if evidence shows incorrect or misleading answers.
- Reconcile the v1.1 hardening plan's contradictory H6 header/completion text and
  replace its arbitrary commit-count acceptance claim with a truthful history
  statement. Do not rewrite the historical tag or fabricate history.

**Acceptance checks**

- Observable CLI, retrieval, evaluation, and rebuild behavior remains stable.
- Complexity is removed from `Ingestor` and transaction callers rather than
  shifted into extra wrappers.
- No arbitrary coverage, complexity, or line-count target is used as a release
  claim.
- Ruff, full deterministic tests, lock check, and build pass.

**Status:** `not started`

### P6 — GitHub security automation and portfolio documentation

**Goal:** Make risks, architecture, provenance, and verification legible to a
public reviewer.

**Repository changes**

- Add a concise `SECURITY.md` covering supported versions, private disclosure,
  the local-only trust boundary, document-processing risks, and dependency
  response policy.
- Add Dependabot configuration for Python, GitHub Actions, and Docker inputs at
  a low-noise cadence.
- Add CodeQL or an equivalently focused Python static-analysis workflow without
  Ollama or corpus downloads.
- Update README architecture, threat boundary, installation, quick demo,
  citations, limitations, evaluation methodology, LocalRAG attribution, corpus
  licenses, and reproducibility commands.
- Clearly distinguish deterministic expected-fact checks, human semantic
  review, citation validity, and Recall@5.
- Update changelog and package version to `1.2.0` only after the implementation
  contract is stable.
- Audit every tracked file and Git diff for absolute paths, credentials,
  generated corpora, model files, caches, databases, pickles, binaries, and
  misleading claims.

**External GitHub settings — separately authorized write step**

- Enable Dependabot alerts and security updates where the repository plan
  permits them.
- Enable code scanning and secret scanning where available.
- Verify workflow permissions remain least privilege.
- Do not change repository visibility in this milestone.

**Acceptance checks**

- GitHub security settings are verified through the repository API/UI rather
  than assumed.
- Security and dependency workflows pass on the exact branch commit.
- README commands work from a clean checkout without private data.
- Attribution and licenses remain accurate.
- Final project naming and repository description are proposed for owner review,
  not changed automatically.

**Status:** `not started`

### P7 — Final evidence, pull request, and private release candidate

**Goal:** Prove the exact v1.2 candidate before public visibility changes.

**Procedure**

- Run `uv sync --locked --extra dev`, lock validation, Ruff, the deterministic
  suite, package build, vulnerability audit, Bandit, tracked-secret scan, and
  `git diff --check`.
- Build and smoke-test the optional non-root container.
- If P3 changed vector storage, retrieval, embeddings, or answer behavior, run
  exactly one clean FastAPI evaluation and one clean Clippy evaluation using the
  established release settings. Capture sanitized reports and compare them to
  v1.1 evidence.
- If those behaviors did not change, preserve v1.1 model-backed evidence and
  explicitly state why rerunning it would add no signal.
- Verify citation validity, Recall@5, semantic factuality, refusal behavior,
  no-change ingestion, expanded source display, and recovery messages.
- Create focused professional commits without milestone, task-complete, AI, or
  noisy micro-commit wording.
- Push `codex/v1.2-hardening`, open a reviewed pull request to `main`, and wait
  for all GitHub checks on the exact head commit.
- Review the full PR diff, dependency delta, generated artifacts, and GitHub
  security results. Resolve failures through focused follow-up commits.
- Merge while preserving the reviewed commit history. Confirm `main` matches
  the accepted tree and the repository is still private.

**Release gates**

- All P0–P6 acceptance checks pass.
- No unresolved critical/high vulnerability is present unless the owner has
  signed off on a documented, architecture-specific residual-risk exception.
- No medium/high static-security finding remains unexplained.
- Model-backed gates, when required, remain at least: 100% citation validity,
  90% Recall@5, and 85% manually reviewed factuality for each corpus.
- CI and security workflows pass for the exact merged commit.
- The repository remains private.

**Status:** `not started`

### P8 — Owner-approved public release

**Goal:** Make the reviewed repository public without surprising exposure.

**Mandatory pause**

Present the owner with:

- the merged commit SHA and successful CI/security checks;
- the final dependency and residual-risk report;
- evaluation and benchmark evidence, including anything not rerun;
- the exact tracked-file and secret-scan result;
- the proposed repository name, description, topics, and release notes;
- confirmation that issues, Actions logs/artifacts, commit metadata, branches,
  tags, and history will become publicly visible.

Do not continue until the owner explicitly says to make the repository public.

**After approval**

- Change visibility from private to public.
- Immediately verify the anonymous repository view, README rendering, license,
  default branch, Actions, security settings, releases, and absence of unintended
  files.
- Create and push an annotated `v1.2.0` tag on the accepted `main` commit only
  after successful CI and visibility verification.
- Create the GitHub release from reviewed notes and link reproducible evidence.
- Verify the tag and release resolve to the exact accepted commit.

**Acceptance checks**

- An unauthenticated viewer can clone the repository and complete the documented
  deterministic setup/checks.
- The public security posture and limitations are accurate.
- `v1.1.0` remains unchanged and `v1.2.0` points to the accepted public release.
- No post-publication emergency correction is required.

**Status:** `not started`

## Final completion checklist

- [ ] P0 audited baseline frozen on `codex/v1.2-hardening`
- [ ] P1 compatibility and empty-source defects fixed
- [ ] P2 local vector-backend decision recorded
- [ ] P3 complete generation transaction and Chroma mitigation finished
- [ ] P4 supply-chain and container hardening finished
- [ ] P5 focused maintainability cleanup finished
- [ ] P6 GitHub security automation and portfolio documentation finished
- [ ] P7 private release candidate merged with all gates passing
- [ ] Owner explicitly approved public visibility
- [ ] P8 anonymous public verification and `v1.2.0` release finished

## Implementation handoff

After owner approval, begin with exactly this instruction:

```text
Read V1_2_PUBLIC_RELEASE_PLAN.md completely. Implement only P0: “Freeze and
reproduce the audited baseline.” Follow its scope and acceptance checks exactly.
Do not invoke Ollama or run model-backed evaluations. Do not modify v1.1 history
or tags. Do not change GitHub settings or repository visibility. Update only
P0's status when every acceptance check passes, then stop and report the branch,
starting commit, commands, evidence, changed files, and remaining risks. Do not
begin P1.
```
