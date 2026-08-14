from __future__ import annotations

import json
import re
import time
from pathlib import Path, PurePosixPath

from .generation import validate_citations
from .index_state import IndexIdentity, IndexStateStore
from .models import AnswerResult, SearchHit
from .ollama import OllamaError
from .service import RAGService


class DatasetValidationError(ValueError):
    """The evaluation dataset does not satisfy the evidence-target contract."""


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


def normalize_source_path(value: str) -> str:
    """Normalize a relative evidence path while rejecting traversal and absolutes."""

    if not isinstance(value, str) or not value.strip():
        raise DatasetValidationError("evidence target source must be a non-empty path")
    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise DatasetValidationError(f"evidence target source must be relative: {value!r}")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        raise DatasetValidationError("evidence target source must name a file")
    return "/".join(parts)


def normalize_heading_path(value: str) -> str:
    """Normalize heading paths for exact, case-insensitive comparison."""

    if not isinstance(value, str) or not value.strip():
        raise DatasetValidationError("evidence target heading must be non-empty")
    without_anchor = re.sub(r"\s*\{\s*#[^}]+\}\s*$", "", value.strip())
    parts = re.split(r"\s*>\s*", without_anchor)
    normalized: list[str] = []
    for part in parts:
        part = re.sub(r"`([^`]*)`", r"\1", part)
        part = re.sub(r"[*_~]", "", part)
        part = re.sub(r"\s+", " ", part).strip()
        if part:
            normalized.append(part.casefold())
    if not normalized:
        raise DatasetValidationError("evidence target heading must be non-empty")
    return " > ".join(normalized)


def _validate_target(value: object, record_id: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise DatasetValidationError(f"record {record_id!r} evidence target must be an object")
    if "chunk_id" in value:
        raise DatasetValidationError(
            f"record {record_id!r} evidence targets cannot contain chunk_id"
        )
    if "source" not in value or "heading" not in value:
        raise DatasetValidationError(
            f"record {record_id!r} evidence target requires source and heading"
        )
    return {
        "source": normalize_source_path(value["source"]),
        "heading": normalize_heading_path(value["heading"]),
    }


def validate_dataset(value: object) -> dict[str, object]:
    """Validate and normalize the public evaluation dataset contract."""

    if not isinstance(value, dict):
        raise DatasetValidationError("dataset must be a JSON object")
    dataset_name = value.get("dataset")
    version = value.get("version")
    records = value.get("records")
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise DatasetValidationError("dataset requires a non-empty dataset name")
    if not isinstance(version, str) or not version.strip():
        raise DatasetValidationError("dataset requires a non-empty version")
    if not isinstance(records, list):
        raise DatasetValidationError("dataset records must be an array")

    normalized_records: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, dict):
            raise DatasetValidationError(f"record {index} must be an object")
        record_id = raw_record.get("id")
        question = raw_record.get("question")
        in_scope = raw_record.get("in_scope")
        targets = raw_record.get("evidence_targets")
        expected_facts = raw_record.get("expected_facts")
        if not isinstance(record_id, str) or not record_id.strip():
            raise DatasetValidationError(f"record {index} requires a non-empty id")
        if record_id in seen_ids:
            raise DatasetValidationError(f"duplicate dataset record id: {record_id}")
        seen_ids.add(record_id)
        if not isinstance(question, str) or not question.strip():
            raise DatasetValidationError(f"record {record_id!r} requires a question")
        if not isinstance(in_scope, bool):
            raise DatasetValidationError(f"record {record_id!r} requires boolean in_scope")
        if not isinstance(targets, list):
            raise DatasetValidationError(
                f"record {record_id!r} requires evidence_targets array"
            )
        if in_scope and not targets:
            raise DatasetValidationError(
                f"in-scope record {record_id!r} requires at least one evidence target"
            )
        if not isinstance(expected_facts, list) or not all(
            isinstance(fact, str) and fact.strip() for fact in expected_facts
        ):
            raise DatasetValidationError(
                f"record {record_id!r} requires expected_facts as text array"
            )
        normalized_records.append(
            {
                "id": record_id,
                "question": question.strip(),
                "in_scope": in_scope,
                "evidence_targets": [_validate_target(target, record_id) for target in targets],
                "expected_facts": [fact.strip() for fact in expected_facts],
            }
        )
    normalized = dict(value)
    normalized["dataset"] = dataset_name.strip()
    normalized["version"] = version.strip()
    normalized["records"] = normalized_records
    return normalized


def _relative_hit_source(source: str, corpus_root: Path | None) -> str:
    candidate = Path(source)
    if candidate.is_absolute() and corpus_root is not None:
        try:
            candidate = candidate.resolve().relative_to(corpus_root.resolve())
        except ValueError:
            pass
    raw = candidate.as_posix()
    if candidate.is_absolute():
        raw = raw.lstrip("/")
    try:
        return normalize_source_path(raw)
    except DatasetValidationError:
        return raw.replace("\\", "/").lstrip("/")


def match_evidence_targets(
    targets: list[dict[str, str]],
    hits: list[SearchHit],
    corpus_root: Path | None = None,
) -> dict[str, object] | None:
    """Return the first exact source-plus-heading target matched in the top five."""

    normalized_targets = {
        (normalize_source_path(target["source"]), normalize_heading_path(target["heading"])): target
        for target in targets
    }
    for rank, hit in enumerate(hits[:5], start=1):
        source = _relative_hit_source(hit.chunk.source, corpus_root)
        try:
            heading = normalize_heading_path(hit.chunk.heading_path)
        except DatasetValidationError:
            continue
        target = normalized_targets.get((source, heading))
        if target is not None:
            return {
                "source": normalize_source_path(target["source"]),
                "heading": normalize_heading_path(target["heading"]),
                "rank": rank,
            }
    return None


def _corpus_root(settings: object, corpus: dict[str, object]) -> Path | None:
    name = corpus.get("name")
    if not isinstance(name, str) or not name:
        return None
    corpus_path = getattr(settings, "corpus_path", None)
    if isinstance(corpus_path, Path):
        return corpus_path / name
    return None


def _active_identity(settings: object) -> IndexIdentity | None:
    state_path = getattr(settings, "index_state_path", None)
    if not isinstance(state_path, Path):
        return None
    try:
        return IndexStateStore(state_path).load()
    except (OSError, ValueError) as exc:
        raise DatasetValidationError("active index provenance is invalid; run ingest --rebuild") from exc


def _validate_dataset_corpus(dataset: dict[str, object], identity: IndexIdentity | None) -> None:
    expected = dataset.get("corpus")
    if not isinstance(expected, dict) or not expected:
        return
    actual = identity.corpus_provenance if identity else None
    if actual is None:
        raise DatasetValidationError(
            "dataset corpus is pinned but the active index has no corpus provenance; "
            "run tracerag ingest PATH --rebuild"
        )
    mismatches = [
        field
        for field in ("name", "commit", "allowed_path")
        if expected.get(field) is not None and expected.get(field) != getattr(actual, field)
    ]
    if mismatches:
        raise DatasetValidationError(
            "dataset corpus does not match the active index ("
            + ", ".join(mismatches)
            + "); run tracerag corpus fetch NAME and tracerag ingest PATH --rebuild"
        )


def _active_corpus(identity: IndexIdentity | None) -> dict[str, object]:
    if identity is None or identity.corpus_provenance is None:
        return {}
    return identity.corpus_provenance.as_dict()


def _sanitize_sources(sources: object, corpus_root: Path | None) -> list[dict[str, object]]:
    if not isinstance(sources, list):
        return []
    sanitized: list[dict[str, object]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        item = dict(source)
        value = item.get("source")
        if isinstance(value, str):
            source_path = Path(value)
            item["source"] = (
                _relative_hit_source(value, corpus_root)
                if not source_path.is_absolute() or corpus_root is not None
                else source_path.name
            )
        sanitized.append(item)
    return sanitized


def _read_corpus_manifest(settings: object) -> dict[str, object]:
    """Compatibility shim retained for callers; active index is the source of truth."""
    return _active_corpus(_active_identity(settings))


def _index_provenance(settings: object, identity: IndexIdentity | None = None) -> dict[str, object]:
    state_path = getattr(settings, "index_state_path", None)
    identity_dict: dict[str, object] | None = identity.as_dict() if identity else None
    error = None
    if identity_dict is None and isinstance(state_path, Path):
        try:
            loaded = IndexStateStore(state_path).load()
            identity_dict = loaded.as_dict() if loaded else None
        except (OSError, ValueError) as exc:
            error = str(exc)
    cache_path = getattr(settings, "embedding_cache_path", None)
    cache: dict[str, object] = {}
    if isinstance(cache_path, Path):
        cache["path"] = cache_path.name
    max_bytes = getattr(settings, "embedding_cache_max_bytes", None)
    if isinstance(max_bytes, int):
        cache["max_bytes"] = max_bytes
    embedding_model = getattr(settings, "embed_model", None)
    if isinstance(embedding_model, str):
        cache["embedding_model"] = embedding_model
    result: dict[str, object] = {
        "index": identity_dict,
        "cache": cache,
    }
    if error:
        result["index_error"] = error
    return result


def run_evaluation(
    service: RAGService,
    dataset_path: Path,
    output_dir: Path,
    limit: int | None = None,
    report_stem: str | None = None,
) -> dict[str, object]:
    try:
        raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"could not read dataset: {dataset_path}") from exc
    dataset = validate_dataset(raw_dataset)
    cases: list[dict[str, object]] = []
    retrieved_relevant = 0
    retrieval_total = 0
    factual_total = 0
    out_of_scope_total = 0
    out_of_scope_refused = 0
    all_records = dataset["records"]
    assert isinstance(all_records, list)
    records = all_records[:limit] if limit else all_records
    identity = _active_identity(service.settings)
    _validate_dataset_corpus(dataset, identity)
    corpus = _active_corpus(identity)
    corpus_root = _corpus_root(service.settings, corpus)
    provenance = {
        "dataset": {
            "name": dataset["dataset"],
            "version": dataset["version"],
            "corpus": dataset.get("corpus", {}),
        },
        "corpus": corpus,
        **_index_provenance(service.settings, identity),
    }
    for record in records:
        assert isinstance(record, dict)
        started = time.perf_counter()
        question = str(record["question"])
        hits = service.retrieve(question, top_k=5)
        targets = record["evidence_targets"]
        assert isinstance(targets, list)
        matched_target = match_evidence_targets(targets, hits, corpus_root)
        relevant = matched_target is not None if record["in_scope"] else True
        in_scope = bool(record["in_scope"])
        if in_scope:
            retrieval_total += 1
            retrieved_relevant += int(relevant)
        else:
            out_of_scope_total += 1
        result: AnswerResult
        model_error: str | None = None
        try:
            result = service.ask(question, hits=hits)
        except OllamaError as exc:
            model_error = str(exc)
            result = AnswerResult(
                question,
                "",
                hits,
                True,
                f"Model error: {exc}",
                service.settings.generation_model,
            )
        if in_scope:
            expected_facts = record["expected_facts"]
            assert isinstance(expected_facts, list)
            factual = (
                _fact_present(str(expected_facts[0]), result.answer)
                if expected_facts
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
                "question": question,
                "in_scope": in_scope,
                "status": "pass" if factual and citation_valid and relevant else "fail",
                "retrieval_relevant": relevant,
                "evidence_targets": targets,
                "expected_facts": record["expected_facts"],
                "matched_target": matched_target,
                "citation_valid": citation_valid,
                "factual": factual,
                "refused": result.refused,
                "answer": result.answer,
                "model_error": model_error,
                "sources": _sanitize_sources(result.as_dict()["sources"], corpus_root),
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
    index = provenance.get("index")
    index_schema = index.get("schema_version") if isinstance(index, dict) else None
    report: dict[str, object] = {
        "schema_version": 2,
        "dataset": dataset["dataset"],
        "dataset_version": dataset["version"],
        "dataset_corpus": dataset.get("corpus", {}),
        "records_evaluated": len(records),
        "corpus": corpus,
        "index_schema_version": index_schema,
        "provenance": provenance,
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
            "deterministic expected-fact proxy; semantic review recorded in "
            f"docs/manual-review-{dataset['dataset'].removesuffix('-v1')}.md"
        ),
        "release_gate": {
            "citation_validity": citation_validity >= 1.0,
            "recall_at_5": retrieved_relevant / max(1, retrieval_total) >= 0.9,
            "factuality": factual_total / in_scope_total >= 0.85,
        },
        "cases": cases,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = report_stem or str(dataset["dataset"])
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "evaluation"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# TraceRAG evaluation",
        "",
        f"Dataset: `{report['dataset']}` (version `{report['dataset_version']}`)",
        f"Corpus pin: `{corpus.get('name', 'unknown')}` @ `{corpus.get('commit', 'unknown')}`",
        f"Index schema: `{index_schema or 'unversioned'}`",
        f"Index generation: `{(index or {}).get('generation', 'unknown') if isinstance(index, dict) else 'unknown'}`",
        f"Cache path: `{provenance.get('cache', {}).get('path', 'unknown') if isinstance(provenance.get('cache'), dict) else 'unknown'}`",
        "",
        "| Metric | Value | Gate |",
        "|---|---:|:---:|",
    ]
    for name, value in report["metrics"].items():
        lines.append(
            f"| {name} | {float(value):.1%} | {'PASS' if report['release_gate'][name] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| ID | Status | Evidence targets | Matched target | Failure |",
            "|---|---|---|---|---|",
        ]
    )
    for case in cases:
        targets_text = "; ".join(
            f"{target['source']}#{target['heading']}" for target in case["evidence_targets"]
        )
        matched = case["matched_target"]
        matched_text = (
            f"{matched['source']}#{matched['heading']} (rank {matched['rank']})"
            if matched
            else ""
        )
        lines.append(
            f"| {case['id']} | {case['status']} | {targets_text} | "
            f"{matched_text} | {case['failure_class'] or ''} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
