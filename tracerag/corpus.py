from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

FASTAPI_URL = "https://github.com/fastapi/fastapi.git"
FASTAPI_COMMIT = "f336ff831c4af3d4f625c2593a27b1e0cae93eb7"


def fetch_fastapi(destination: Path) -> dict[str, str]:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", FASTAPI_URL, str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", "--depth", "1", "origin", FASTAPI_COMMIT],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", FASTAPI_COMMIT],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = {
        "name": "fastapi",
        "url": FASTAPI_URL,
        "commit": FASTAPI_COMMIT,
        "license": "MIT",
        "fetched_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(FASTAPI_COMMIT.encode()).hexdigest(),
    }
    (destination / ".tracerag-corpus.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest
