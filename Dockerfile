FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY tracerag ./tracerag
COPY evals ./evals
RUN uv sync --locked --no-dev
ENTRYPOINT ["/app/.venv/bin/tracerag"]
