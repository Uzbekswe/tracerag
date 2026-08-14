from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .persistence import atomic_write_json

logger = logging.getLogger(__name__)
CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CacheStatus:
    entries: int
    bytes: int
    max_bytes: int


class EmbeddingCache:
    def __init__(self, directory: Path, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("embedding cache size must be positive")
        self.directory = directory
        self.max_bytes = max_bytes
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(
        self,
        text_hash: str,
        model: str,
        dimension: int | None,
        chunking_version: str,
        preprocessing_version: str,
    ) -> list[float] | None:
        matches: list[Path] = []
        for path in self._entries():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise TypeError("cache entry must be an object")
                if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
                    raise ValueError("unsupported cache schema")
                key = payload["key"]
                if not self._key_matches(
                    key,
                    text_hash,
                    model,
                    dimension,
                    chunking_version,
                    preprocessing_version,
                ):
                    continue
                matches.append(path)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                logger.warning("ignoring corrupt embedding cache entry: %s", path)
                path.unlink(missing_ok=True)

        # If the dimension is not known yet, reuse only an unambiguous entry.
        if len(matches) != 1:
            return None
        path = matches[0]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("cache entry must be an object")
            if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
                raise ValueError("unsupported cache schema")
            vector = payload["vector"]
            if (
                not isinstance(vector, list)
                or not vector
                or any(
                    isinstance(value, bool) or not isinstance(value, (float, int))
                    for value in vector
                )
            ):
                raise ValueError("invalid cached vector")
            os.utime(path, None)
            return [float(value) for value in vector]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning("ignoring corrupt embedding cache entry: %s", path)
            path.unlink(missing_ok=True)
            return None

    def put(
        self,
        text_hash: str,
        model: str,
        dimension: int,
        chunking_version: str,
        preprocessing_version: str,
        vector: list[float],
    ) -> None:
        if dimension <= 0 or len(vector) != dimension:
            raise ValueError("embedding vector dimension does not match its cache key")
        key = {
            "text_hash": text_hash,
            "model": model,
            "dimension": dimension,
            "chunking_version": chunking_version,
            "preprocessing_version": preprocessing_version,
        }
        digest = hashlib.sha256(
            json.dumps(key, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        payload = {"schema_version": CACHE_SCHEMA_VERSION, "key": key, "vector": vector}
        self._write_atomic(self.directory / f"{digest}.json", payload)
        self._evict()

    def status(self) -> CacheStatus:
        entries = self._entries()
        return CacheStatus(
            entries=len(entries),
            bytes=sum(path.stat().st_size for path in entries if path.exists()),
            max_bytes=self.max_bytes,
        )

    def clear(self) -> int:
        removed = 0
        for path in self._entries():
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    def _entries(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    def _evict(self) -> None:
        entries = self._entries()
        total = sum(path.stat().st_size for path in entries if path.exists())
        for path in sorted(entries, key=lambda item: item.stat().st_mtime):
            if total <= self.max_bytes:
                break
            size = path.stat().st_size if path.exists() else 0
            path.unlink(missing_ok=True)
            total -= size

    @staticmethod
    def _key_matches(
        key: object,
        text_hash: str,
        model: str,
        dimension: int | None,
        chunking_version: str,
        preprocessing_version: str,
    ) -> bool:
        if not isinstance(key, dict):
            return False
        return (
            key.get("text_hash") == text_hash
            and key.get("model") == model
            and (dimension is None or key.get("dimension") == dimension)
            and key.get("chunking_version") == chunking_version
            and key.get("preprocessing_version") == preprocessing_version
        )

    @staticmethod
    def _write_atomic(path: Path, payload: dict[str, object]) -> None:
        atomic_write_json(path, payload, indent=None)
