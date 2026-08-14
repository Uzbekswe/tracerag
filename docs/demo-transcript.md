# TraceRAG v1.1 demo transcript

This transcript records the verified native workflow. For an interactive recording,
run the commands in [`demo-script.md`](demo-script.md) in one terminal session.

```text
$ uv run tracerag doctor
Python 3.13.2                         OK
Ollama http://localhost:11434         OK
Embedding model nomic-embed-text      installed
Generation model qwen3:4b             installed

$ uv run tracerag corpus fetch fastapi
Fetched FastAPI corpus at commit f336ff831c4af3d4f625c2593a27b1e0cae93eb7

$ uv run tracerag ingest data/corpus/fastapi/docs/en/docs
Indexed 2736 chunks from 155 parsed files (154 with chunks, 1 empty HTML-only file).

$ uv run tracerag ingest data/corpus/fastapi/docs/en/docs
No changes: 155 files skipped, 0 chunks embedded.

$ uv run tracerag documents
Sources 155 | Chunks 2736 | Indexed with chunks 154 | Empty parsed 1 | Current 154

$ uv run tracerag ask "What kind of web framework is FastAPI?"
FastAPI is a modern, high-performance web framework for building APIs with
Python based on standard Python type hints [1].

$ uv run tracerag ask "What kind of web framework is FastAPI?" --show-source 1
[1] docs/en/docs/index.md | FastAPI | score 0.016
Preview: FastAPI is a modern, high-performance web framework for building APIs
with Python based on standard Python type hints.

$ uv run tracerag ask "What is the private database password used by FastAPI?" --show-nearest
TraceRAG refusal: No retrieved passage met the evidence threshold.

$ uv run tracerag corpus fetch clippy
Fetched Clippy corpus at commit d2c4d1532d89488a56ec2c3ca12757117fc0b4e2

$ uv run tracerag ingest data/corpus/clippy/book/src/development
Indexed 339 chunks from 24 Markdown files.

$ TRAGERAG_DATA_DIR=data/h5-fastapi TRAGERAG_MODEL_CONTEXT=2048 \
  TRAGERAG_MAX_ANSWER_TOKENS=96 uv run tracerag eval --dataset fastapi-v1 \
  --output-dir reports/h5-fastapi
{"citation_validity": 1.0, "recall_at_5": 1.0, "factuality": 0.9714285714285714}

$ TRAGERAG_DATA_DIR=data/h5-clippy TRAGERAG_MODEL_CONTEXT=2048 \
  TRAGERAG_MAX_ANSWER_TOKENS=96 uv run tracerag eval --dataset clippy-v1 \
  --output-dir reports/h5-clippy
{"citation_validity": 1.0, "recall_at_5": 1.0, "factuality": 1.0}

$ TRAGERAG_DATA_DIR=data/h5-fastapi uv run tracerag benchmark --corpus fastapi --output-dir docs
Benchmark complete: unchanged ingest 0.07s, 0 embedding calls
```

The generated reports contain the complete per-case timings, source metadata,
and refusal diagnostics. A plain-text capture of the native terminal session is
preserved in [`demo-recording.txt`](demo-recording.txt); an optional video
version can still be made from the same short script. The FastAPI deterministic
proxy records one semantically supported expected-fact miss; both corpus
release gates pass.
