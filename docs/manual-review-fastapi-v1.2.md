# FastAPI manual factuality review

This is the human-review companion to the 2026-08-15 P7 run of
`docs/evidence/fastapi-v1.2.json`. The deterministic report checks expected facts
and exact source-plus-heading retrieval; this table records the separate
semantic review decision.

| ID | Verdict | Review note |
|---|:---:|---|
| f01 | PASS | Framework description is supported by the cited introduction. |
| f02 | PASS | The cited tutorial contains the pip install command. |
| f03 | PASS | App construction and the development command are cited. |
| f04 | PASS | Decorator parameters and path-operation metadata are cited. |
| f05 | PASS | Pydantic validation, serialization, and response filtering are cited. |
| f06 | PASS | Query syntax, parsing, validation, and required parameters are cited. |
| f07 | PASS | Path-variable syntax and function binding are cited. |
| f08 | PASS | Request-body declarations and supported methods are cited. |
| f09 | PASS | Response-model filtering and inclusion controls are cited. |
| f10 | PASS | Named and explicit response status configuration is cited. |
| f11 | PASS | Request and response header declarations are cited. |
| f12 | PASS | Response cookies and Cookie parameter models are cited. |
| f13 | PASS | Dependency execution and result injection are cited. |
| f14 | PASS | Security(), Depends(), and OAuth2 scope configuration are cited. |
| f15 | PASS | Scope semantics and FastAPI authorization integration are cited. |
| f16 | PASS | The answer is semantically supported; the deterministic fact proxy missed the literal `BackgroundTasks` token. |
| f17 | PASS | Middleware request-before/response-after behavior is cited. |
| f18 | PASS | CORSMiddleware and its key parameters are cited. |
| f19 | PASS | WebSocket implementation guidance is cited, with scope stated cautiously. |
| f20 | PASS | Event-handler lifecycle and startup gating are cited. |
| f21 | PASS | Lifespan protocol, context manager, and app scope are cited. |
| f22 | PASS | async/await and concurrent execution are cited. |
| f23 | PASS | UploadFile attributes and file declarations are cited. |
| f24 | PASS | Form models, Form, and extraction behavior are cited. |
| f25 | PASS | JSONResponse and response serialization are cited. |
| f26 | PASS | The cited custom-handler passage supports `@app.exception_handler()` and global exception handling. |
| f27 | PASS | OpenAPI, interactive documentation, and client generation are cited. |
| f28 | PASS | Tags, OpenAPI grouping, and documentation organization are cited. |
| f29 | PASS | The cited OpenAPI extension passages support modifying and caching the generated schema. |
| f30 | PASS | TestClient, request data, and dependency overrides are cited. |
| f31 | PASS | Deployment strategies and operational concerns are cited. |
| f32 | PASS | Async concurrency and worker-process parallelism are cited. |
| f33 | PASS | Temporary Response headers and response merging are cited. |
| f34 | PASS | JSON Schema and OpenAPI example rendering are cited. |
| f35 | PASS | Metadata parameters such as title are cited. |

Result: 35/35 in-scope answers passed this semantic review (100%). The
machine-readable report records 35/35 deterministic expected-fact matches for
this run. Out-of-scope refusal records are diagnostic and remain outside the
semantic denominator.
