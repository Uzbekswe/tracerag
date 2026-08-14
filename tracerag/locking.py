from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import ConcurrentIngestError


@contextmanager
def ingest_lock(path: Path) -> Iterator[None]:
    """Acquire an exclusive, non-blocking lock for one persistent ingest path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in {11, 35}:
                raise ConcurrentIngestError(
                    "another ingest is already running for this data directory"
                ) from exc
            raise
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
