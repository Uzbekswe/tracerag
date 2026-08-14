# TraceRAG v1.2 P2 — Local Vector Backend Spike

## Scope

This CPU-only spike compares the current embedded Chroma client with a
stdlib-only SQLite exact-search candidate. It does not modify production
TraceRAG code, dependencies, lockfiles, runtime models, or persisted data. It
does not start Ollama or any vector HTTP service.

Reproducibility note:

The comparison was run before the production backend change with the temporary
spike harness. The harness was intentionally removed after the decision so the
runtime and development lock no longer carry Chroma's vulnerable dependency;
the measured output below is the preserved evidence for that decision.

The fixture is deterministic: 1,288 records, 768-dimensional vectors, four
queries, and top-k 10. That approximates the recorded FastAPI index size rather
than measuring a toy collection.

## Vector-store contract at the seam

The candidate must support the durable generation interface required by P3:

| Operation | Current embedded adapter | SQLite candidate |
| --- | --- | --- |
| Create staged generation | Persistent Chroma collection | SQLite database/table |
| Add vectors and metadata | `collection.add`/`upsert` | SQLite parameterized insert/upsert |
| Replace a source | Delete source IDs, then upsert | Delete by metadata/source key, then upsert |
| Top-k search | Chroma cosine/HNSW query | Exact cosine scan with deterministic tie-break |
| Validate | Count and collection reopen | Count, dimensions, metadata parse, reopen |
| Activate/open | Resolve collection from generation manifest | Resolve database from generation manifest |
| Delete obsolete generation | Delete collection | Delete generation database |

The temporary harness directly exercised staged creation, vector/metadata
persistence, reopen, validation, top-k search, and generation deletion. Source
replacement is covered by the P3 production tests; the preserved measurements
are sufficient to record the feasibility decision without keeping Chroma in the
runtime dependency graph.

## Measured result

Run on the Apple Silicon development machine with Python 3.13.2, SQLite 3.45.3,
and Chroma 1.5.9. Timings are one local sample for comparison, not universal
performance promises.

| Metric | Chroma `PersistentClient` | SQLite stdlib exact |
| --- | ---: | ---: |
| Fixture rows | 1,288 | 1,288 |
| Vector dimension | 768 | 768 |
| Index bytes | 10,631,720 | 5,324,800 |
| Stage/write | 576.754 ms | 23.900 ms |
| Reopen + validate | 4.898 ms | 0.242 ms |
| Four top-k queries | 5.969 ms | 404.199 ms |
| Delete generation | 10.594 ms | 0.051 ms |

The SQLite candidate produced exact top-k parity for all four queries:

- exact top-10 matches: 4/4;
- top-1 matches: 4/4;
- top-10 set overlap: 10/10 for every query.

The candidate's pure-Python exact search is approximately 100 ms per query at
this corpus size. That is slower than Chroma but still bounded for a local
single-user CLI; the O(records × dimensions) cost must be measured again if
the product expands beyond compact documentation corpora.

## Dependency and footprint findings

The current lock resolves 89 packages. Chroma's dependency tree includes
`grpcio`, Kubernetes client libraries, ONNX Runtime, OpenTelemetry, tokenizers,
uvicorn, and related transitive packages. Representative installed sizes are:

| Package area | Size |
| --- | ---: |
| `chromadb` | 4.1 MB (removed after the decision) |
| `chromadb_rust_bindings` | 50 MB |
| `onnxruntime` | 70 MB |
| `grpc` | 39 MB |
| `kubernetes` | 41 MB |
| Measured subset | approximately 204 MB |

The SQLite candidate uses only Python's standard library and adds no package,
native extension, network client, or model runtime. Replacing Chroma would not
automatically remove every shared dependency, so P3 must regenerate the lock
and verify the actual reduction rather than claim the entire 89-package tree
will disappear.

## Safety and portability checks

- The candidate imports only `sqlite3`, `struct`, `math`, and other standard
  library modules; it starts no listener and has no HTTP client.
- Static inspection of the production tree found no `HttpClient`,
  `trust_remote_code`, `pickle`, or Chroma server invocation.
- The only relevant development listener is Ollama on loopback port 11434;
  the spike did not create a TraceRAG or Chroma listener. Other listeners on the
  machine belong to unrelated desktop processes.
- The SQLite format is ordinary on-disk data with parameterized SQL and packed
  float vectors; it does not require pickle deserialization.

## P2 decision

**Recommend replacement in P3 with a SQLite-backed exact local vector adapter.**

The candidate satisfies the exercised generation/search contract, matches
Chroma's top-k results on the representative fixture, materially reduces index
footprint, adds no dependency, and removes the affected Chroma package from
the intended public runtime. The performance tradeoff is explicit and bounded
for the current corpus scale.

P3 must still prove source replacement, staged failure cleanup, dimensional
validation, atomic generation activation, and query behavior through the
production interface. Because vector storage changes retrieval implementation,
P7 must run one final clean FastAPI and Clippy model-backed evaluation before
public release, as required by the release plan.

## Remaining risks

- Exact search is linear in corpus size and dimension; larger corpora may need
  a measured optimization or a different local adapter.
- The spike does not establish crash recovery or concurrent-writer behavior;
  those belong to P3's deep generation transaction tests.
- Chroma remains the production backend until P3 is implemented and accepted.
- No public release or residual-risk exception is authorized by this spike.
