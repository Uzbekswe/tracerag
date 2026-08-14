import json
from pathlib import Path


def test_manual_review_templates_cover_each_in_scope_case() -> None:
    fastapi = Path("docs/manual-review-fastapi-v1.2.md").read_text(encoding="utf-8")
    clippy = Path("docs/manual-review-clippy-v1.2.md").read_text(encoding="utf-8")
    fastapi_dataset = json.loads(Path("evals/dataset/fastapi-v1.json").read_text(encoding="utf-8"))
    clippy_dataset = json.loads(Path("evals/dataset/clippy-v1.json").read_text(encoding="utf-8"))

    for record in fastapi_dataset["records"]:
        if record["in_scope"]:
            assert f"| {record['id']} |" in fastapi
    for record in clippy_dataset["records"]:
        if record["in_scope"]:
            assert f"| {record['id']} |" in clippy


def test_evidence_reports_do_not_expose_absolute_paths() -> None:
    for path in Path("docs/evidence").glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "/private/" not in text
