#!/usr/bin/env bash
set -euo pipefail

# Reproducible short recording for the pinned FastAPI demo corpus.
# The index must already exist; build it with the README quickstart first.
export TRAGERAG_DATA_DIR="${TRAGERAG_DATA_DIR:-data/demo}"
export TRAGERAG_TOP_K="${TRAGERAG_TOP_K:-1}"

run() {
  printf '\n$ %s\n' "$1"
  shift
  "$@" 2>&1 | sed -E \
    -e 's#/Users/[^ ]+#data/corpus/fastapi…#g' \
    -e 's#/private/[^ ]+#data/corpus/fastapi…#g'
}

run "uv run tracerag doctor" uv run tracerag doctor
run "uv run tracerag documents" uv run tracerag documents
run "uv run tracerag ask \"What kind of web framework is FastAPI?\"" \
  uv run tracerag ask "What kind of web framework is FastAPI?"
printf '\n$ uv run tracerag ask "What is the private database password used by FastAPI?" --show-nearest\n'
set +e
TRAGERAG_DATA_DIR="$TRAGERAG_DATA_DIR" uv run tracerag ask \
  "What is the private database password used by FastAPI?" --show-nearest 2>&1 \
  | sed -E \
      -e 's#/Users/[^ ]+#data/corpus/fastapi…#g' \
      -e 's#/private/[^ ]+#data/corpus/fastapi…#g'
status=${PIPESTATUS[0]}
set -e
test "$status" -eq 2
run "uv run tracerag ingest data/corpus/fastapi/docs/en/docs" \
  uv run tracerag ingest data/corpus/fastapi/docs/en/docs
