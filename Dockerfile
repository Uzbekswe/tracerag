# Python 3.13.15 slim-trixie; reviewed 2026-08-15. Keep the digest until the
# image is deliberately re-reviewed with `docker buildx imagetools inspect`.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4
# uv 0.11.15; reviewed 2026-08-15.
COPY --from=ghcr.io/astral-sh/uv:0.11.15@sha256:e590846f4776907b254ac0f44b5b380347af5d90d668138ca7938d1b0c2f98d3 /uv /uvx /bin/
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 tracerag \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin tracerag
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY tracerag ./tracerag
COPY evals ./evals
RUN uv sync --locked --no-dev
RUN mkdir -p /app/data /app/documents \
    && chown tracerag:tracerag /app/data \
    && chmod 750 /app/data \
    && chmod 555 /app/documents
USER tracerag:tracerag
ENTRYPOINT ["/app/.venv/bin/tracerag"]
