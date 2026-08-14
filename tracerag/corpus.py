from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .index_state import CorpusProvenance

FASTAPI_URL = "https://github.com/fastapi/fastapi.git"
FASTAPI_COMMIT = "f336ff831c4af3d4f625c2593a27b1e0cae93eb7"
CLIPPY_URL = "https://github.com/rust-lang/rust-clippy.git"
CLIPPY_COMMIT = "d2c4d1532d89488a56ec2c3ca12757117fc0b4e2"
CORPUS_MANIFEST_FILENAME = ".tracerag-corpus.json"


@dataclass(frozen=True)
class CorpusProfile:
    name: str
    url: str
    commit: str
    license: str
    allowed_path: str
    allowed_suffixes: tuple[str, ...] = ()

    @property
    def allowlist(self) -> str:
        return f"{self.allowed_path}/**"

    @property
    def display_name(self) -> str:
        return "FastAPI" if self.name == "fastapi" else self.name.title()


@dataclass(frozen=True)
class CorpusContext:
    """Validated, path-bound metadata for a fetched corpus profile."""

    root: Path
    allowed_root: Path
    manifest: dict[str, object]

    @property
    def provenance(self) -> CorpusProvenance:
        return CorpusProvenance.from_dict(self.manifest)


class CorpusManifestError(ValueError):
    """A corpus manifest is invalid or the requested path is not allowlisted."""


FASTAPI_PROFILE = CorpusProfile(
    name="fastapi",
    url=FASTAPI_URL,
    commit=FASTAPI_COMMIT,
    license="MIT",
    allowed_path="docs/en/docs",
)
CLIPPY_PROFILE = CorpusProfile(
    name="clippy",
    url=CLIPPY_URL,
    commit=CLIPPY_COMMIT,
    license="MIT OR Apache-2.0",
    allowed_path="book/src/development",
    allowed_suffixes=(".md", ".markdown"),
)
CORPUS_PROFILES: dict[str, CorpusProfile] = {
    FASTAPI_PROFILE.name: FASTAPI_PROFILE,
    CLIPPY_PROFILE.name: CLIPPY_PROFILE,
}


def get_profile(name: str) -> CorpusProfile:
    try:
        return CORPUS_PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(CORPUS_PROFILES))
        raise ValueError(f"unknown corpus profile {name!r}; choose from {choices}") from exc


def _manifest_root(path: Path) -> Path | None:
    candidate = path.resolve(strict=False)
    current = candidate if candidate.is_dir() else candidate.parent
    for parent in (current, *current.parents):
        manifest_path = parent / CORPUS_MANIFEST_FILENAME
        if manifest_path.is_file():
            return parent
    return None


def _validate_manifest(root: Path) -> dict[str, object]:
    manifest_path = root / CORPUS_MANIFEST_FILENAME
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusManifestError(f"invalid corpus manifest: {manifest_path}") from exc
    if not isinstance(value, dict):
        raise CorpusManifestError("corpus manifest must be a JSON object")
    if value.get("schema_version", 1) != 1:
        raise CorpusManifestError("unsupported corpus manifest schema")
    name = value.get("name")
    try:
        profile = get_profile(name) if isinstance(name, str) else None
    except ValueError as exc:
        raise CorpusManifestError(str(exc)) from exc
    if profile is None:
        raise CorpusManifestError("corpus manifest profile name is missing")
    expected = {
        "url": profile.url,
        "commit": profile.commit,
        "license": profile.license,
        "allowed_path": profile.allowed_path,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise CorpusManifestError(
                f"corpus manifest {field} does not match pinned {profile.name} profile"
            )
    if value.get("allowlist") not in (None, [profile.allowlist]):
        raise CorpusManifestError("corpus manifest allowlist does not match profile")
    allowed_root = root / profile.allowed_path
    if not allowed_root.is_dir():
        raise CorpusManifestError(f"corpus allowlist root is missing: {profile.allowed_path}")
    return value


def resolve_corpus_context(path: Path) -> CorpusContext | None:
    """Resolve the nearest fetched corpus manifest and enforce its allowlist.

    Paths without a manifest remain valid as unprofiled local documents. A path
    inside a corpus checkout but outside its allowlisted subtree is rejected.
    """

    root = _manifest_root(path)
    if root is None:
        return None
    manifest = _validate_manifest(root)
    allowed_root = (root / str(manifest["allowed_path"])).resolve()
    candidate = path.resolve(strict=False)
    try:
        candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise CorpusManifestError(f"ingest path is outside the allowlist: {path}") from exc
    return CorpusContext(root=root, allowed_root=allowed_root, manifest=manifest)


def fetch_corpus(profile: CorpusProfile | str, destination: Path) -> dict[str, object]:
    """Fetch one immutable profile and validate its allowlisted source tree."""

    if isinstance(profile, str):
        profile = get_profile(profile)

    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", profile.url, str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", "--depth", "1", "origin", profile.commit],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "--detach", profile.commit],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    checked_out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if checked_out != profile.commit:
        raise ValueError(
            f"checked out commit {checked_out or '(unknown)'} does not match "
            f"pinned {profile.commit}"
        )

    allowed_root = destination / profile.allowed_path
    if not allowed_root.is_dir():
        raise ValueError(
            f"allowlisted corpus path is missing for {profile.name}: {profile.allowed_path}"
        )
    files = sorted(path for path in allowed_root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(
            f"allowlisted corpus path is empty for {profile.name}: {profile.allowed_path}"
        )
    resolved_root = allowed_root.resolve()
    for path in files:
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"allowlisted corpus path escapes its root: {path}") from exc
    if profile.allowed_suffixes:
        allowed_suffixes = {suffix.lower() for suffix in profile.allowed_suffixes}
        unexpected = [
            path.relative_to(destination).as_posix()
            for path in files
            if path.suffix.lower() not in allowed_suffixes
        ]
        if unexpected:
            raise ValueError(
                f"allowlisted corpus path contains unsupported files: {', '.join(unexpected)}"
            )

    relative_files = [path.relative_to(destination).as_posix() for path in files]
    manifest: dict[str, object] = {
        "schema_version": 1,
        "name": profile.name,
        "url": profile.url,
        "commit": profile.commit,
        "license": profile.license,
        "allowed_path": profile.allowed_path,
        "allowlist": [profile.allowlist],
        "file_count": len(relative_files),
        "files": relative_files,
        "fetched_at": datetime.now(UTC).isoformat(),
        # Retain the v1 manifest field while making the pinned identity explicit.
        "sha256": hashlib.sha256(profile.commit.encode()).hexdigest(),
    }
    (destination / CORPUS_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def fetch_fastapi(destination: Path) -> dict[str, object]:
    return fetch_corpus(FASTAPI_PROFILE, destination)


def fetch_clippy(destination: Path) -> dict[str, object]:
    return fetch_corpus(CLIPPY_PROFILE, destination)
