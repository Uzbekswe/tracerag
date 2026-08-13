from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .generation import validate_citations
from .models import AnswerResult
from .ollama import OllamaError
from .service import RAGService


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _fact_present(expected: str, answer: str) -> bool:
    """Allow simple English pluralization in deterministic fact checks."""
    expected_words = _words(expected)
    answer_words = _words(answer)
    return all(
        word in answer_words
        or word + "s" in answer_words
        or word.endswith("y")
        and word[:-1] + "ies" in answer_words
        for word in expected_words
    )


def run_evaluation(
    service: RAGService,
    dataset_path: Path,
    output_dir: Path,
    limit: int | None = None,
) -> dict[str, object]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases: list[dict[str, object]] = []
    retrieved_relevant = 0
    retrieval_total = 0
    factual_total = 0
    out_of_scope_total = 0
    out_of_scope_refused = 0
    records = dataset["records"][:limit] if limit else dataset["records"]
    for record in records:
        started = time.perf_counter()
        hits = service.retrieve(str(record["question"]), top_k=5)
        expected_sources = {str(value) for value in record.get("expected_sources", [])}
        retrieved_sources = {hit.chunk.source for hit in hits}
        relevant = (
            any(
                any(expected in source for expected in expected_sources)
                for source in retrieved_sources
            )
            if expected_sources
            else True
        )
        in_scope = bool(record.get("in_scope", True))
        if in_scope:
            retrieval_total += 1
            retrieved_relevant += int(relevant)
        else:
            out_of_scope_total += 1
        result: AnswerResult
        model_error: str | None = None
        try:
            result = service.ask(str(record["question"]), hits=hits)
        except OllamaError as exc:
            model_error = str(exc)
            result = AnswerResult(
                str(record["question"]),
                "",
                hits,
                True,
                f"Model error: {exc}",
                service.settings.generation_model,
            )
        if in_scope:
            factual = (
                _fact_present(str(record["expected_facts"][0]), result.answer)
                if record.get("expected_facts")
                else not result.refused
            )
            citation_valid = not result.refused and validate_citations(
                result.answer, len(result.sources)
            )
        else:
            factual = result.refused and model_error is None
            citation_valid = result.refused and model_error is None
            out_of_scope_refused += int(factual)
        if in_scope:
            factual_total += int(factual)
        if model_error:
            failure_class = "model_error"
        elif factual and citation_valid and relevant:
            failure_class = None
        elif in_scope and not relevant:
            failure_class = "retrieval_miss"
        elif (not in_scope and not result.refused) or (in_scope and result.refused):
            failure_class = "refusal_error"
        elif not citation_valid:
            failure_class = "citation_mismatch"
        else:
            failure_class = "unsupported_claim"
        cases.append(
            {
                "id": record["id"],
                "question": record["question"],
                "status": "pass" if factual and citation_valid and relevant else "fail",
                "retrieval_relevant": relevant,
                "citation_valid": citation_valid,
                "factual": factual,
                "refused": result.refused,
                "answer": result.answer,
                "model_error": model_error,
                "sources": result.as_dict()["sources"],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "failure_class": None if factual and citation_valid and relevant else failure_class,
            }
        )
        print(f"evaluated {len(cases)}/{len(records)}: {record['id']}", flush=True)
    in_scope_total = retrieval_total or 1
    # In-scope refusal is a citation failure; out-of-scope refusal is a pass
    # for refusal accuracy and is excluded from the citation denominator.
    citation_validity = (
        sum(
            bool(case["citation_valid"])
            for case, record in zip(cases, records, strict=False)
            if record.get("in_scope", True)
        )
        / in_scope_total
    )
    corpus_manifest = service.settings.manifest_path
    corpus = {}
    if corpus_manifest.exists():
        corpus = json.loads(corpus_manifest.read_text(encoding="utf-8"))
    report: dict[str, object] = {
        "schema_version": 1,
        "dataset": dataset.get("dataset", "fastapi-v1"),
        "records_evaluated": len(records),
        "corpus": corpus,
        "models": {
            "embedding": service.settings.embed_model,
            "generation": service.settings.generation_model,
        },
        "config": {
            "top_k": 5,
            "min_retrieval_score": service.settings.min_retrieval_score,
            "model_context": service.settings.model_context,
        },
        "metrics": {
            "citation_validity": citation_validity,
            "recall_at_5": retrieved_relevant / max(1, retrieval_total),
            "factuality": factual_total / in_scope_total,
        },
        "diagnostics": {
            "in_scope_cases": retrieval_total,
            "out_of_scope_cases": out_of_scope_total,
            "out_of_scope_refusal_accuracy": out_of_scope_refused / max(1, out_of_scope_total),
            "generated_answers": sum(int(bool(case["answer"])) for case in cases),
        },
        "factuality_method": (
            "deterministic expected-fact proxy; semantic review recorded in docs/manual-review.md"
        ),
        "release_gate": {
            "citation_validity": citation_validity >= 1.0,
            "recall_at_5": retrieved_relevant / max(1, retrieval_total) >= 0.9,
            "factuality": factual_total / in_scope_total >= 0.85,
        },
        "cases": cases,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# TraceRAG evaluation",
        "",
        f"Dataset: `{report['dataset']}`",
        "",
        "| Metric | Value | Gate |",
        "|---|---:|:---:|",
    ]
    for name, value in report["metrics"].items():
        lines.append(
            f"| {name} | {float(value):.1%} | {'PASS' if report['release_gate'][name] else 'FAIL'} |"
        )
    lines.extend(["", "## Cases", "", "| ID | Status | Failure |", "|---|---|---|"])
    lines.extend(
        f"| {case['id']} | {case['status']} | {case['failure_class'] or ''} |" for case in cases
    )
    (output_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def compare_baseline(report: dict[str, object], baseline_path: Path) -> list[str]:
    """Return regression messages for metrics that fall below a stored baseline."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    regressions: list[str] = []
    current_metrics = report.get("metrics", {})
    baseline_metrics = baseline.get("metrics", {})
    for name, previous in baseline_metrics.items():
        current = current_metrics.get(name)
        if current is not None and float(current) < float(previous):
            regressions.append(
                f"{name} regressed from {float(previous):.3f} to {float(current):.3f}"
            )
    return regressions
