# TraceRAG v1 demo transcript

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
Indexed 2736 chunks from 155 files.

$ uv run tracerag ask "What kind of web framework is FastAPI?"
FastAPI is a modern, high-performance web framework for building APIs with
Python based on standard Python type hints [1].

$ uv run tracerag ask "What is the private database password used by FastAPI?" --show-nearest
TraceRAG refusal: No retrieved passage met the evidence threshold.

$ uv run tracerag eval --dataset fastapi-v1
{"citation_validity": 1.0, "recall_at_5": 1.0, "factuality": 1.0}
```

The generated reports contain the complete per-case timings, source metadata,
and refusal diagnostics. A plain-text capture of the native terminal session is
preserved in [`demo-recording.txt`](demo-recording.txt); an optional video
version can still be made from the same short script.
