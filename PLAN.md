# TraceRAG v1 — Portfolio-Grade Local Citation Assistant

## Current implementation status

- Automated implementation and verification are complete in this workspace.
- Verified locally: `uv sync --locked`, Ruff, 16 pytest tests, lock validation, Compose syntax, `doctor`, supported cited JSON output, and unsupported-question refusal (exit code 2).
- Latest H5 evidence is captured under `docs/evidence/`: FastAPI reached 100% citation validity, 100% Recall@5, and 97.1% deterministic factuality; Clippy reached 100% for citation validity, Recall@5, and deterministic factuality.
- Both corpus runs meet the release gates. FastAPI's one deterministic expected-fact proxy miss is semantically supported and documented in the manual review.
- A real native terminal session is captured in `docs/demo-recording.txt`; the short video version remains optional presentation polish.

## Summary

- Build a command-oriented terminal application with Rich output—not a web or native desktop UI.
- Use a reproducible, pinned FastAPI repository checkout; the public demo/evaluation indexes its canonical English documentation subtree (`docs/en/docs`) while retaining the rest of the checkout for provenance and future corpus profiles.
- Objective: a local-first CLI that answers only from indexed Markdown/text-PDF evidence, displays numbered citations with previews, and refuses unsupported questions.
- Default models: Ollama `nomic-embed-text` for embeddings and `qwen3:4b` for generation; both are configurable.
- Reuse ideas and selectively adapt MIT-licensed LocalRAG components, retaining copyright/license notices and documenting attribution. The public demo corpus is fetched at a pinned FastAPI commit, whose repository is MIT-licensed.

## Phases and milestones

1. **Foundation — runnable local project**
   - Create a clean Python 3.13 project named `tracerag`, using `uv`, Typer, Rich, Pydantic settings, pytest, Ruff, and a locked dependency file.
   - Add explicit configuration for Ollama endpoint, model tags, local data directory, collection name, retrieval threshold, and output limits.
   - Provide `tracerag doctor` to verify Python environment, Ollama reachability, required model availability, writable data paths, and optional Docker availability.
   - Acceptance: a clean clone can install dependencies, run `doctor`, and receive actionable setup errors without silently downloading models.

2. **Corpus and ingestion — reproducible evidence**
   - Implement `tracerag corpus fetch fastapi` to shallow-clone a pinned FastAPI commit, record repository URL, commit SHA, license, and fetch timestamp in a local manifest.
   - Implement `tracerag ingest PATH` for Markdown and text-layer PDFs only; detect image-only/scanned PDFs and report them as unsupported rather than performing OCR.
   - Parse Markdown structurally by headings, preserve heading breadcrumbs, chunk text deterministically, embed chunks in batches, and persist vectors in local Chroma.
   - Store source path, content hash, chunk ID, heading path, chunk ordinal, and corpus provenance with every chunk.
   - Build a local BM25 index from the same chunks after ingest; `tracerag documents` reports sources, chunk counts, content-change state, and ingestion failures.
   - Acceptance: re-ingesting unchanged files is idempotent; a changed source replaces only its own chunks; source metadata always survives retrieval.

3. **Trust-first retrieval and answering — the actual product**
   - Use hybrid retrieval by default: Chroma semantic search + BM25 lexical search, combined with reciprocal-rank fusion.
   - Start with structural chunking, `top_k=5`, and heading-section expansion; do not include query rewriting, HyDE, rerankers, agents, MCP, GraphRAG, plugins, Kubernetes, or multi-user features in v1.
   - Build the generator prompt from only retrieved evidence; require concise answers and source markers matching retrieved chunks.
   - Implement `tracerag ask "QUESTION"` with Rich output:
     - answer text with `[1]`, `[2]` markers;
     - a source panel listing path, heading, score, and short evidence preview;
     - `--show-source N` to print the complete cited chunk/section;
     - `--json` for machine-readable answer, sources, model/config provenance, and timings.
   - Enforce a calibrated retrieval threshold: when no evidence meets it, skip generation and return a clear refusal. `--show-nearest` may reveal the best non-qualifying matches for diagnosis.
   - Acceptance: every generated answer has at least one valid source marker; unsupported questions do not invoke the answer model.

4. **Evaluation — prove the claim**
   - Add a versioned 40-question FastAPI evaluation dataset with manually authored expected facts, expected source passages, and in-scope/out-of-scope labels.
   - Implement `tracerag eval` to run retrieval and answer generation against the pinned corpus and write a versioned local JSON/Markdown report containing corpus SHA, models, config, timings, retrieved chunks, citations, and per-case outcomes.
   - Release gate:
     - citation validity: **100%**;
     - retrieval recall@5: **≥90%**;
     - manually reviewed answer factuality: **≥85%**;
     - publish all failures and their class: retrieval miss, unsupported claim, citation mismatch, or refusal error.
   - Use deterministic checks for citation validity, source recall, and normalized expected-fact matching. Any local LLM judge is optional diagnostic output only and cannot determine release success.
   - Acceptance: the project can compare a candidate run against a committed baseline and fail non-zero when the release gate regresses.

5. **Distribution and portfolio proof**
   - Make native `uv` + Ollama setup the primary path; add a minimal optional Compose stack only after native behavior passes.
   - Compose includes the TraceRAG app, Ollama, and persistent named volumes; no separate MCP, monitoring, Kubernetes, or external Chroma service.
   - Write a README with a 60-second quickstart, architecture diagram, local-data boundary, citations/refusal behavior, measured evaluation report, limitations, and LocalRAG attribution.
   - Record a short terminal demo showing corpus fetch, ingest, an evidence-backed answer, source expansion, an unsupported-question refusal, and evaluation output.
   - Acceptance: a reviewer can reproduce the demo locally from the README and understand the trust claim without reading the implementation.

## Public interfaces

```text
tracerag doctor
tracerag corpus fetch fastapi
tracerag ingest PATH [--collection NAME]
tracerag documents [--collection NAME]
tracerag ask QUESTION [--show-source N] [--show-nearest] [--json]
tracerag eval [--dataset fastapi-v1] [--baseline PATH]
```

The reusable core owns parsing, chunking, storage, retrieval, prompt construction, answer generation, and evaluation. CLI handlers remain thin so a future API or UI can reuse the same services without a rewrite.

## Test plan

- Unit tests: config validation, Markdown/PDF extraction boundaries, deterministic chunk IDs, content replacement, vector/BM25 fusion, citation-marker validation, source previews, refusal threshold, and JSON output.
- Integration tests: local Ollama model availability guard, ingest → ask → cited answer lifecycle, unsupported-question refusal, and evaluation-report generation.
- Regression tests: fixed retrieval fixtures and the 40-question gate; preserve failures as named cases.
- Manual acceptance: run the complete FastAPI demo on the target 8 GB Apple Silicon machine and capture the terminal recording from that run.

## Defaults and boundaries

- Local-first means documents, embeddings, vector storage, retrieval, and generation remain on the machine by default.
- Text PDFs are supported; scanned PDFs, OCR, DOCX, web UI, agent loops, MCP, cloud defaults, high availability, and multi-user permissions are deferred.
- The model choice is a reproducible baseline, not a claim of universal quality; future larger-model profiles must be measured against the same dataset before replacing the default.
- No fixed calendar estimate: phases complete only when their acceptance criteria and quality gate pass.
