# TraceRAG evaluation

Dataset: `fastapi-v1` (version `1.1.0`)
Corpus pin: `fastapi` @ `f336ff831c4af3d4f625c2593a27b1e0cae93eb7`
Index schema: `2`
Index generation: `e0efee77f2694aa292fd7ecd83588b26`
Cache path: `embedding-cache`

| Metric | Value | Gate |
|---|---:|:---:|
| citation_validity | 100.0% | PASS |
| recall_at_5 | 100.0% | PASS |
| factuality | 97.1% | PASS |

## Cases

| ID | Status | Evidence targets | Matched target | Failure |
|---|---|---|---|---|
| f01 | pass | docs/en/docs/index.md#fastapi | docs/en/docs/index.md#fastapi (rank 1) |  |
| f02 | pass | docs/en/docs/tutorial/index.md#tutorial - user guide { #tutorial-user-guide } > install fastapi | docs/en/docs/tutorial/index.md#tutorial - user guide { #tutorial-user-guide } > install fastapi (rank 2) |  |
| f03 | pass | docs/en/docs/tutorial/first-steps.md#first steps { #first-steps } > recap, step by step { #recap-step-by-step } > step 2: create a fastapi "instance" | docs/en/docs/tutorial/first-steps.md#first steps { #first-steps } > recap, step by step { #recap-step-by-step } > step 2: create a fastapi "instance" (rank 1) |  |
| f04 | pass | docs/en/docs/tutorial/path-operation-configuration.md#path operation configuration | docs/en/docs/tutorial/path-operation-configuration.md#path operation configuration (rank 2) |  |
| f05 | pass | docs/en/docs/tutorial/response-model.md#response model - return type { #response-model-return-type } > return type and data filtering { #return-type-and-data-filtering } > fastapi data filtering | docs/en/docs/tutorial/response-model.md#response model - return type { #response-model-return-type } > return type and data filtering { #return-type-and-data-filtering } > fastapi data filtering (rank 2) |  |
| f06 | pass | docs/en/docs/tutorial/query-params.md#query parameters | docs/en/docs/tutorial/query-params.md#query parameters (rank 1) |  |
| f07 | pass | docs/en/docs/tutorial/path-params.md#path parameters | docs/en/docs/tutorial/path-params.md#path parameters (rank 3) |  |
| f08 | pass | docs/en/docs/tutorial/body.md#request body | docs/en/docs/tutorial/body.md#request body (rank 3) |  |
| f09 | pass | docs/en/docs/tutorial/response-model.md#response model - return type { #response-model-return-type } > other return type annotations { #other-return-type-annotations } > annotate a response subclass | docs/en/docs/tutorial/response-model.md#response model - return type { #response-model-return-type } > other return type annotations { #other-return-type-annotations } > annotate a response subclass (rank 1) |  |
| f10 | pass | docs/en/docs/tutorial/response-status-code.md#response status code | docs/en/docs/tutorial/response-status-code.md#response status code (rank 5) |  |
| f11 | pass | docs/en/docs/tutorial/header-params.md#header parameters | docs/en/docs/tutorial/header-params.md#header parameters (rank 3) |  |
| f12 | pass | docs/en/docs/tutorial/cookie-params.md#cookie parameters { #cookie-parameters } > declare cookie parameters | docs/en/docs/tutorial/cookie-params.md#cookie parameters { #cookie-parameters } > declare cookie parameters (rank 3) |  |
| f13 | pass | docs/en/docs/tutorial/dependencies/index.md#dependencies { #dependencies } > first steps | docs/en/docs/tutorial/dependencies/index.md#dependencies { #dependencies } > first steps (rank 1) |  |
| f14 | pass | docs/en/docs/reference/dependencies.md#dependencies - depends() and security() > security() | docs/en/docs/reference/dependencies.md#dependencies - depends() and security() > security() (rank 1) |  |
| f15 | pass | docs/en/docs/advanced/security/oauth2-scopes.md#oauth2 scopes | docs/en/docs/advanced/security/oauth2-scopes.md#oauth2 scopes (rank 1) |  |
| f16 | fail | docs/en/docs/tutorial/background-tasks.md#background tasks { #background-tasks } > dependency injection | docs/en/docs/tutorial/background-tasks.md#background tasks { #background-tasks } > dependency injection (rank 1) | unsupported_claim |
| f17 | pass | docs/en/docs/tutorial/middleware.md#middleware | docs/en/docs/tutorial/middleware.md#middleware (rank 2) |  |
| f18 | pass | docs/en/docs/tutorial/cors.md#cors (cross-origin resource sharing) { #cors-cross-origin-resource-sharing } > use corsmiddleware | docs/en/docs/tutorial/cors.md#cors (cross-origin resource sharing) { #cors-cross-origin-resource-sharing } > use corsmiddleware (rank 2) |  |
| f19 | pass | docs/en/docs/advanced/websockets.md#websockets | docs/en/docs/advanced/websockets.md#websockets (rank 4) |  |
| f20 | pass | docs/en/docs/advanced/events.md#lifespan events { #lifespan-events } > alternative events (deprecated) { #alternative-events-deprecated } > startup event | docs/en/docs/advanced/events.md#lifespan events { #lifespan-events } > alternative events (deprecated) { #alternative-events-deprecated } > startup event (rank 1) |  |
| f21 | pass | docs/en/docs/advanced/events.md#lifespan events { #lifespan-events } > technical details | docs/en/docs/advanced/events.md#lifespan events { #lifespan-events } > technical details (rank 1) |  |
| f22 | pass | docs/en/docs/async.md#concurrency and async / await | docs/en/docs/async.md#concurrency and async / await (rank 3) |  |
| f23 | pass | docs/en/docs/tutorial/request-files.md#request files { #request-files } > file parameters with uploadfile { #file-parameters-with-uploadfile } > uploadfile | docs/en/docs/tutorial/request-files.md#request files { #request-files } > file parameters with uploadfile { #file-parameters-with-uploadfile } > uploadfile (rank 2) |  |
| f24 | pass | docs/en/docs/tutorial/request-forms.md#form data | docs/en/docs/tutorial/request-forms.md#form data (rank 3) |  |
| f25 | pass | docs/en/docs/advanced/custom-response.md#custom response - html, stream, file, others { #custom-response-html-stream-file-others } > available responses { #available-responses } > jsonresponse | docs/en/docs/advanced/custom-response.md#custom response - html, stream, file, others { #custom-response-html-stream-file-others } > available responses { #available-responses } > jsonresponse (rank 1) |  |
| f26 | pass | docs/en/docs/tutorial/handling-errors.md#handling errors { #handling-errors } > install custom exception handlers | docs/en/docs/tutorial/handling-errors.md#handling errors { #handling-errors } > install custom exception handlers (rank 1) |  |
| f27 | pass | docs/en/docs/reference/openapi/index.md#openapi | docs/en/docs/reference/openapi/index.md#openapi (rank 4) |  |
| f28 | pass | docs/en/docs/tutorial/path-operation-configuration.md#path operation configuration { #path-operation-configuration } > tags | docs/en/docs/tutorial/path-operation-configuration.md#path operation configuration { #path-operation-configuration } > tags (rank 3) |  |
| f29 | pass | docs/en/docs/how-to/extending-openapi.md#extending openapi | docs/en/docs/how-to/extending-openapi.md#extending openapi (rank 2) |  |
| f30 | pass | docs/en/docs/tutorial/testing.md#testing { #testing } > testing: extended example { #testing-extended-example } > extended testing file | docs/en/docs/tutorial/testing.md#testing { #testing } > testing: extended example { #testing-extended-example } > extended testing file (rank 1) |  |
| f31 | pass | docs/en/docs/deployment/concepts.md#deployments concepts | docs/en/docs/deployment/concepts.md#deployments concepts (rank 5) |  |
| f32 | pass | docs/en/docs/async.md#concurrency and async / await { #concurrency-and-async-await } > asynchronous code { #asynchronous-code } > concurrency + parallelism: web + machine learning | docs/en/docs/async.md#concurrency and async / await { #concurrency-and-async-await } > asynchronous code { #asynchronous-code } > concurrency + parallelism: web + machine learning (rank 1) |  |
| f33 | pass | docs/en/docs/advanced/response-headers.md#response headers { #response-headers } > use a response parameter | docs/en/docs/advanced/response-headers.md#response headers { #response-headers } > use a response parameter (rank 1) |  |
| f34 | pass | docs/en/docs/tutorial/schema-extra-example.md#declare request example data { #declare-request-example-data } > technical details { #technical-details } > pydantic and fastapi examples | docs/en/docs/tutorial/schema-extra-example.md#declare request example data { #declare-request-example-data } > technical details { #technical-details } > pydantic and fastapi examples (rank 1) |  |
| f35 | pass | docs/en/docs/tutorial/path-params-numeric-validations.md#path parameters and numeric validations { #path-parameters-and-numeric-validations } > declare metadata | docs/en/docs/tutorial/path-params-numeric-validations.md#path parameters and numeric validations { #path-parameters-and-numeric-validations } > declare metadata (rank 2) |  |
| f36 | pass |  |  |  |
| f37 | pass |  |  |  |
| f38 | pass |  |  |  |
| f39 | pass |  |  |  |
| f40 | pass |  |  |  |
