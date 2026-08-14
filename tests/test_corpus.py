import json
from pathlib import Path

import pytest

from tracerag.corpus import (
    CLIPPY_COMMIT,
    CLIPPY_PROFILE,
    CLIPPY_URL,
    FASTAPI_COMMIT,
    FASTAPI_PROFILE,
    FASTAPI_URL,
    fetch_clippy,
    fetch_fastapi,
    resolve_corpus_context,
)


def test_fastapi_corpus_identity_is_pinned() -> None:
    assert FASTAPI_URL.endswith("fastapi.git")
    assert len(FASTAPI_COMMIT) == 40
    assert FASTAPI_PROFILE.allowed_path == "docs/en/docs"
    assert FASTAPI_PROFILE.license == "MIT"


def test_clippy_profile_is_pinned_and_auditable() -> None:
    assert CLIPPY_URL == "https://github.com/rust-lang/rust-clippy.git"
    assert CLIPPY_COMMIT == "d2c4d1532d89488a56ec2c3ca12757117fc0b4e2"
    assert CLIPPY_PROFILE.allowed_path == "book/src/development"
    assert CLIPPY_PROFILE.license == "MIT OR Apache-2.0"


def test_clippy_fetch_writes_manifest_for_allowlisted_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command, cwd=None, **_kwargs):
        if command[:2] == ["git", "clone"]:
            destination = Path(command[-1])
            allowed = destination / "book/src/development"
            allowed.mkdir(parents=True)
            (allowed / "lint-authoring.md").write_text("# Lint authoring\n", encoding="utf-8")
            (allowed / "tests.md").write_text("# Tests\n", encoding="utf-8")
            (destination / "README.md").write_text("repository root\n", encoding="utf-8")
        return type("Completed", (), {"stdout": CLIPPY_COMMIT + "\n"})()

    monkeypatch.setattr("tracerag.corpus.subprocess.run", fake_run)

    manifest = fetch_clippy(tmp_path / "clippy")

    assert manifest["name"] == "clippy"
    assert manifest["commit"] == CLIPPY_COMMIT
    assert manifest["license"] == "MIT OR Apache-2.0"
    assert manifest["allowed_path"] == "book/src/development"
    assert manifest["allowlist"] == ["book/src/development/**"]
    assert manifest["file_count"] == 2
    assert manifest["files"] == [
        "book/src/development/lint-authoring.md",
        "book/src/development/tests.md",
    ]
    saved = tmp_path.joinpath("clippy", ".tracerag-corpus.json")
    assert saved.exists()


def test_clippy_fetch_rejects_missing_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command, **_kwargs):
        if command[:2] == ["git", "clone"]:
            Path(command[-1]).mkdir(parents=True)
        return type("Completed", (), {"stdout": CLIPPY_COMMIT + "\n"})()

    monkeypatch.setattr("tracerag.corpus.subprocess.run", fake_run)

    with pytest.raises(ValueError, match="allowlisted corpus path"):
        fetch_clippy(tmp_path / "clippy")


def test_fastapi_fetch_keeps_v1_profile_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command, **_kwargs):
        if command[:2] == ["git", "clone"]:
            destination = Path(command[-1])
            (destination / "docs/en/docs").mkdir(parents=True)
            (destination / "docs/en/docs/index.md").write_text("# FastAPI\n", encoding="utf-8")
        return type("Completed", (), {"stdout": FASTAPI_COMMIT + "\n"})()

    monkeypatch.setattr("tracerag.corpus.subprocess.run", fake_run)

    manifest = fetch_fastapi(tmp_path / "fastapi")

    assert manifest["name"] == "fastapi"
    assert manifest["commit"] == FASTAPI_COMMIT
    assert manifest["allowed_path"] == "docs/en/docs"
    assert manifest["file_count"] == 1


def test_corpus_context_is_path_bound_and_validates_profile(tmp_path: Path) -> None:
    root = tmp_path / "fastapi"
    allowed = root / FASTAPI_PROFILE.allowed_path
    allowed.mkdir(parents=True)
    source = allowed / "guide.md"
    source.write_text("# Guide\n", encoding="utf-8")
    (root / ".tracerag-corpus.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": FASTAPI_PROFILE.name,
                "url": FASTAPI_PROFILE.url,
                "commit": FASTAPI_PROFILE.commit,
                "license": FASTAPI_PROFILE.license,
                "allowed_path": FASTAPI_PROFILE.allowed_path,
                "allowlist": [FASTAPI_PROFILE.allowlist],
                "fetched_at": "2026-08-14T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    context = resolve_corpus_context(source)

    assert context is not None
    assert context.root == root
    assert context.allowed_root == allowed
    assert context.provenance.commit == FASTAPI_COMMIT
    assert context.provenance.allowed_path == FASTAPI_PROFILE.allowed_path

    outside = root / "README.md"
    outside.write_text("outside\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the allowlist"):
        resolve_corpus_context(outside)


def test_unprofiled_path_remains_usable(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n", encoding="utf-8")

    assert resolve_corpus_context(source) is None


def test_evaluation_dataset_has_forty_cases() -> None:
    import json

    dataset = json.loads(Path("evals/dataset/fastapi-v1.json").read_text(encoding="utf-8"))
    assert len(dataset["records"]) == 40
    assert len({record["id"] for record in dataset["records"]}) == 40
    assert all("evidence_targets" in record for record in dataset["records"])
    assert all(
        "chunk_id" not in target
        for record in dataset["records"]
        for target in record["evidence_targets"]
    )


def test_clippy_evaluation_dataset_has_in_scope_and_refusal_cases() -> None:
    import json

    dataset = json.loads(Path("evals/dataset/clippy-v1.json").read_text(encoding="utf-8"))
    assert 10 <= len(dataset["records"]) <= 15
    assert any(record["in_scope"] for record in dataset["records"])
    assert any(not record["in_scope"] for record in dataset["records"])
