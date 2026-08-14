from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .parsers import SUPPORTED_EXTENSIONS
from .persistence import atomic_write_json

SOURCE_STATE_SCHEMA_VERSION = 1


class DocumentStatus(str, Enum):
    """Closed set of source/document states shared by indexing and the CLI."""

    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    CURRENT = "current"
    EMPTY = "empty"


@dataclass(frozen=True)
class SourceRecord:
    source: str
    relative_path: str
    source_hash: str
    corpus_sha: str
    chunk_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "relative_path": self.relative_path,
            "source_hash": self.source_hash,
            "corpus_sha": self.corpus_sha,
            "chunk_count": self.chunk_count,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceRecord:
        if not isinstance(value, dict):
            raise TypeError("source record must be an object")
        source = value.get("source")
        relative_path = value.get("relative_path")
        source_hash = value.get("source_hash")
        corpus_sha = value.get("corpus_sha", "")
        chunk_count = value.get("chunk_count")
        if not all(isinstance(item, str) and item for item in (source, relative_path, source_hash)):
            raise ValueError("source record has missing identity fields")
        if not isinstance(corpus_sha, str):
            raise TypeError("source record corpus provenance must be text")
        if isinstance(chunk_count, bool) or not isinstance(chunk_count, int) or chunk_count < 0:
            raise ValueError("source record chunk count must be non-negative")
        return cls(source, relative_path, source_hash, corpus_sha, chunk_count)


@dataclass(frozen=True)
class FileChange:
    path: Path
    source: str
    relative_path: str
    source_hash: str
    status: DocumentStatus
    previous: SourceRecord | None = None


class SourceStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def load(self) -> dict[str, SourceRecord]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != SOURCE_STATE_SCHEMA_VERSION
            ):
                raise ValueError("unsupported source-state schema")
            raw_records = value.get("sources")
            if not isinstance(raw_records, dict):
                raise TypeError("source-state records must be an object")
            records = {
                str(source): SourceRecord.from_dict(record)
                for source, record in raw_records.items()
            }
            return records
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # A damaged source-state file is safe to recover from: all files are
            # treated as new and the active index is not touched by this loader.
            return {}

    def validate(self) -> None:
        """Raise when this generation's source-state artifact is malformed."""
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != SOURCE_STATE_SCHEMA_VERSION
        ):
            raise ValueError("unsupported source-state schema")
        raw_records = value.get("sources")
        if not isinstance(raw_records, dict):
            raise TypeError("source-state records must be an object")
        for record in raw_records.values():
            SourceRecord.from_dict(record)

    def save(self, records: dict[str, SourceRecord]) -> None:
        payload = {
            "schema_version": SOURCE_STATE_SCHEMA_VERSION,
            "sources": {source: record.as_dict() for source, record in sorted(records.items())},
        }
        atomic_write_json(self.path, payload)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class ChangePlanner:
    @staticmethod
    def plan(
        files: list[Path],
        records: dict[str, SourceRecord],
        root: Path,
        *,
        corpus_sha: str = "",
    ) -> list[FileChange]:
        root = root.resolve()
        current_sources: set[str] = set()
        changes: list[FileChange] = []
        for path in sorted(files):
            resolved = path.resolve()
            source = str(resolved)
            current_sources.add(source)
            relative_path = ChangePlanner._relative_path(resolved, root)
            previous = records.get(source)
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                status = DocumentStatus.UNSUPPORTED
                source_hash = previous.source_hash if previous else ""
            elif previous is None:
                source_hash = SourceStateStore.hash_file(resolved)
                status = DocumentStatus.NEW
            else:
                source_hash = SourceStateStore.hash_file(resolved)
                status = (
                    DocumentStatus.UNCHANGED
                    if previous.source_hash == source_hash and previous.corpus_sha == corpus_sha
                    else DocumentStatus.CHANGED
                )
            changes.append(
                FileChange(resolved, source, relative_path, source_hash, status, previous)
            )

        if root.is_dir():
            for source, previous in sorted(records.items()):
                source_path = Path(source)
                try:
                    source_path.relative_to(root)
                except ValueError:
                    continue
                if source not in current_sources:
                    changes.append(
                        FileChange(
                            source_path,
                            source,
                            previous.relative_path,
                            previous.source_hash,
                            DocumentStatus.MISSING,
                            previous,
                        )
                    )
        return changes

    @staticmethod
    def _relative_path(path: Path, root: Path) -> str:
        try:
            if root.is_dir():
                return path.relative_to(root).as_posix()
        except ValueError:
            pass
        return path.name
