"""Compare the current embedded vector store with a stdlib SQLite candidate.

This is a P2 design spike, not production code. It intentionally uses fixed
vectors and metadata so the same command can be rerun without Ollama or a
network service.
"""

from __future__ import annotations

import argparse
import gc
import importlib.metadata
import json
import math
import platform
import random
import sqlite3
import struct
import tempfile
import time
from pathlib import Path
from typing import Any

import chromadb

ROWS = 1288
DIMENSION = 768
TOP_K = 10
QUERY_INDICES = (3, 127, 643, 1287)


def fixture() -> tuple[list[str], list[str], list[dict[str, object]], list[list[float]]]:
    generator = random.Random(20260814)
    ids = [f"chunk-{index:04d}" for index in range(ROWS)]
    documents = [f"Deterministic document passage {index}." for index in range(ROWS)]
    metadata = [
        {
            "source": "docs/guide.md",
            "heading_path": f"Section {index % 16}",
            "chunk_index": index,
        }
        for index in range(ROWS)
    ]
    vectors = [
        [generator.uniform(-1.0, 1.0) for _ in range(DIMENSION)] for _ in range(ROWS)
    ]
    return ids, documents, metadata, vectors


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def vector_size(vector: list[float]) -> int:
    return len(vector)


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def sqlite_bytes(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def sqlite_vector(value: bytes, dimension: int) -> list[float]:
    return list(struct.unpack(f"<{dimension}f", value))


def file_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def sqlite_search(connection: sqlite3.Connection, query: list[float], top_k: int) -> list[str]:
    rows = connection.execute("SELECT id, vector FROM vectors").fetchall()
    ranked = sorted(
        (
            (cosine(query, sqlite_vector(vector, DIMENSION)), str(identifier))
            for identifier, vector in rows
        ),
        key=lambda item: (-item[0], item[1]),
    )
    return [identifier for _, identifier in ranked[:top_k]]


def validate_sqlite(connection: sqlite3.Connection) -> None:
    count = connection.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
    if count != ROWS:
        raise AssertionError(f"SQLite count mismatch: {count} != {ROWS}")
    for identifier, document, metadata, vector in connection.execute(
        "SELECT id, document, metadata, vector FROM vectors LIMIT 1"
    ):
        if not identifier or not document or not json.loads(metadata):
            raise AssertionError("SQLite metadata contract is invalid")
        if len(sqlite_vector(vector, DIMENSION)) != DIMENSION:
            raise AssertionError("SQLite vector dimension is invalid")


def run_sqlite(
    ids: list[str],
    documents: list[str],
    metadata: list[dict[str, object]],
    vectors: list[list[float]],
    query_vectors: list[list[float]],
    root: Path,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    database = root / "vectors.sqlite3"
    start = time.perf_counter()
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE vectors ("
        "id TEXT PRIMARY KEY, document TEXT NOT NULL, metadata TEXT NOT NULL, vector BLOB NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO vectors VALUES (?, ?, ?, ?)",
        [
            (identifier, document, json.dumps(item, sort_keys=True), sqlite_bytes(vector))
            for identifier, document, item, vector in zip(
                ids, documents, metadata, vectors, strict=True
            )
        ],
    )
    connection.commit()
    write_ms = elapsed_ms(start)

    start = time.perf_counter()
    reopened = sqlite3.connect(database)
    validate_sqlite(reopened)
    open_ms = elapsed_ms(start)

    start = time.perf_counter()
    query_ids = [sqlite_search(reopened, query, TOP_K) for query in query_vectors]
    query_ms = elapsed_ms(start)

    index_bytes = file_bytes(root)
    reopened.close()
    start = time.perf_counter()
    database.unlink()
    delete_ms = elapsed_ms(start)
    return {
        "backend": "sqlite-stdlib-exact",
        "write_ms": write_ms,
        "open_validate_ms": open_ms,
        "query_ms_for_4_queries": query_ms,
        "delete_ms": delete_ms,
        "bytes": index_bytes,
        "query_ids": query_ids,
    }


def run_chroma(
    ids: list[str],
    documents: list[str],
    metadata: list[dict[str, object]],
    vectors: list[list[float]],
    query_vectors: list[list[float]],
    root: Path,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    collection_name = "spike_vectors"
    start = time.perf_counter()
    client = chromadb.PersistentClient(path=str(root))
    collection = client.create_collection(collection_name, metadata={"hnsw:space": "cosine"})
    collection.add(ids=ids, documents=documents, metadatas=metadata, embeddings=vectors)
    write_ms = elapsed_ms(start)
    del collection, client
    gc.collect()

    start = time.perf_counter()
    reopened_client = chromadb.PersistentClient(path=str(root))
    reopened = reopened_client.get_collection(collection_name)
    if reopened.count() != ROWS:
        raise AssertionError(f"Chroma count mismatch: {reopened.count()} != {ROWS}")
    open_ms = elapsed_ms(start)

    start = time.perf_counter()
    query_ids = [
        [str(identifier) for identifier in result]
        for result in reopened.query(
            query_embeddings=query_vectors,
            n_results=TOP_K,
            include=["distances"],
        )["ids"]
    ]
    query_ms = elapsed_ms(start)

    index_bytes = file_bytes(root)
    start = time.perf_counter()
    reopened_client.delete_collection(collection_name)
    delete_ms = elapsed_ms(start)
    del reopened, reopened_client
    gc.collect()
    return {
        "backend": "chromadb-persistent-client",
        "version": importlib.metadata.version("chromadb"),
        "write_ms": write_ms,
        "open_validate_ms": open_ms,
        "query_ms_for_4_queries": query_ms,
        "delete_ms": delete_ms,
        "bytes": index_bytes,
        "query_ids": query_ids,
    }


def parity(left: dict[str, Any], right: dict[str, Any]) -> dict[str, object]:
    exact_top_k = 0
    top_one = 0
    overlaps: list[int] = []
    for expected, actual in zip(left["query_ids"], right["query_ids"], strict=True):
        expected_set = set(expected)
        actual_set = set(actual)
        exact_top_k += expected == actual
        top_one += expected[0] == actual[0]
        overlaps.append(len(expected_set & actual_set))
    return {
        "queries": len(left["query_ids"]),
        "exact_top_k_matches": exact_top_k,
        "top_one_matches": top_one,
        "top_k_overlap": overlaps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON only (the default).")
    parser.parse_args()
    ids, documents, metadata, vectors = fixture()
    query_vectors = [vectors[index] for index in QUERY_INDICES]
    with tempfile.TemporaryDirectory(prefix="tracerag-vector-spike-") as directory:
        root = Path(directory)
        chroma = run_chroma(ids, documents, metadata, vectors, query_vectors, root / "chroma")
        sqlite = run_sqlite(ids, documents, metadata, vectors, query_vectors, root / "sqlite")
    result = {
        "fixture": {"rows": ROWS, "dimension": DIMENSION, "top_k": TOP_K},
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "chroma": chroma,
        "sqlite_candidate": sqlite,
        "parity": parity(chroma, sqlite),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
