import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_dockerfile_uses_reviewed_immutable_inputs_and_non_root_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"^FROM python:3\.13-slim@sha256:[0-9a-f]{64}$", dockerfile, re.MULTILINE)
    assert re.search(
        r"^COPY --from=ghcr\.io/astral-sh/uv:0\.11\.15@sha256:[0-9a-f]{64}",
        dockerfile,
        re.MULTILINE,
    )
    assert "groupadd" in dockerfile and "useradd" in dockerfile
    assert "chown tracerag:tracerag /app/data" in dockerfile
    assert "chmod 555 /app/documents" in dockerfile
    assert "USER tracerag:tracerag" in dockerfile
    assert "ENTRYPOINT [\"/app/.venv/bin/tracerag\"]" in dockerfile


def test_compose_pins_ollama_and_limits_application_writes() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert re.search(r"image: ollama/ollama:0\.12\.6@sha256:[0-9a-f]{64}", compose)
    assert '"127.0.0.1:11434:11434"' in compose
    assert "read_only: true" in compose
    assert "user: \"10001:10001\"" in compose
    assert "./documents:/app/documents:ro" in compose
    assert "tracerag_data:/app/data" in compose


def test_ci_actions_are_commit_pinned_and_security_checks_are_declared() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    action_refs = re.findall(r"^\s*uses:\s*([^\s]+)", workflow, re.MULTILINE)

    assert action_refs
    assert all(re.search(r"@[0-9a-f]{40}$", reference) for reference in action_refs)
    assert "uv run bandit -q -r tracerag -ll" in workflow
    assert "uv export --locked --no-dev --no-emit-project" in workflow


def test_security_audit_documents_subprocess_boundary_and_update_procedure() -> None:
    report = (ROOT / "docs/P4_SECURITY_AUDIT.md").read_text(encoding="utf-8")

    assert "bandit" in report.lower()
    assert "subprocess" in report.lower()
    assert "digest" in report.lower()
    assert "uv lock" in report


def test_codeql_workflow_is_commit_pinned_and_least_privilege() -> None:
    workflow = (ROOT / ".github/workflows/codeql.yml").read_text(encoding="utf-8")
    action_refs = re.findall(r"^\s*uses:\s*([^\s]+)", workflow, re.MULTILINE)

    assert action_refs
    assert all(re.search(r"@[0-9a-f]{40}$", reference) for reference in action_refs)
    assert "contents: read" in workflow
    assert "security-events: write" in workflow
