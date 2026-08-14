# P4 Security and Supply-Chain Record

Reviewed 2026-08-15 on the private `codex/v1.2-hardening` branch.

## Immutable inputs

- `python:3.13-slim` is pinned to the reviewed multi-platform digest in
  `Dockerfile`.
- `ghcr.io/astral-sh/uv:0.11.15` is pinned to its reviewed multi-platform
  digest in `Dockerfile`.
- `ollama/ollama:0.12.6` is pinned to its reviewed multi-platform digest in
  `docker-compose.yml` and remains bound to loopback on the host.
- GitHub Actions are pinned to full commit SHAs with readable release comments.

To update an image, inspect the proposed tag with
`docker buildx imagetools inspect IMAGE:TAG`, record the platform index digest,
rebuild and smoke-test the image, then rerun the deterministic checks and this
audit before changing the pin. Update GitHub Action SHAs only after reviewing
the corresponding release tag and CI result.

## Runtime boundary

The TraceRAG application image runs as UID/GID `10001`, has a read-only root
filesystem, and receives write access only to `/app/data` (plus an in-memory
`/tmp`). The mounted document directory is read-only. Git remains in the image
because `tracerag corpus fetch` intentionally performs a pinned, detached Git
checkout; all arguments are fixed profile values rather than user-provided
shell text. The optional Ollama service is separate, uses its model volume,
and is host-published only on `127.0.0.1`.

## Reproducible checks

```bash
uv lock --check
uv export --locked --no-dev --no-emit-project --format requirements.txt > /tmp/tracerag-runtime-requirements.txt
uv run pip-audit -r /tmp/tracerag-runtime-requirements.txt
uv run bandit -q -r tracerag -ll
docker build -t tracerag:p4 .
docker run --rm tracerag:p4 --help
docker run --rm tracerag:p4 doctor
```

`pip-audit` reports no known vulnerabilities in the locked runtime set at the
review date. Bandit is enforced at medium/high severity (`-ll`); no finding at
that threshold remains. A full low-severity inventory contains only the
explicit Git and Docker probes in `corpus.py`, `benchmark.py`, and `cli.py`,
plus schema-validation `assert` statements in `evaluation.py`. The subprocess
calls use argument arrays, `check=True` where appropriate, bounded timeouts
for the Docker probe, and no shell execution. These findings are documented
rather than globally suppressed.

The image smoke commands do not require Ollama or model inference. P4 does not
claim formal malware certification; it records the repeatable local checks and
their scope.
