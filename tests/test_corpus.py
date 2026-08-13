from pathlib import Path

from tracerag.corpus import FASTAPI_COMMIT, FASTAPI_URL


def test_fastapi_corpus_identity_is_pinned() -> None:
    assert FASTAPI_URL.endswith("fastapi.git")
    assert len(FASTAPI_COMMIT) == 40


def test_evaluation_dataset_has_forty_cases() -> None:
    import json

    dataset = json.loads(Path("evals/dataset/fastapi-v1.json").read_text(encoding="utf-8"))
    assert len(dataset["records"]) == 40
    assert len({record["id"] for record in dataset["records"]}) == 40
