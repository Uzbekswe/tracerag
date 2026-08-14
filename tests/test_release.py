from pathlib import Path

from tracerag import __version__


def test_package_version_is_v12() -> None:
    assert __version__ == "1.2.0"


def test_ci_pins_uv_and_runs_package_build() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'version: "0.11.15"' in workflow
    assert "uv build" in workflow
    assert "ollama" not in workflow.lower()
    assert "benchmark" not in workflow.lower()
    assert "tracerag eval" not in workflow.lower()


def test_public_release_docs_describe_the_security_and_evaluation_contract() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    security = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "Security boundary" in readme
    assert "Evaluation methodology" in readme
    assert "/" in readme
    assert "local-only" in security.lower()
    assert "private disclosure" in security.lower()


def test_dependabot_and_codeql_are_declared_without_model_inference() -> None:
    dependabot = Path(".github/dependabot.yml").read_text(encoding="utf-8")
    codeql = Path(".github/workflows/codeql.yml").read_text(encoding="utf-8")

    assert "package-ecosystem: pip" in dependabot
    assert "package-ecosystem: github-actions" in dependabot
    assert "package-ecosystem: docker" in dependabot
    assert "github/codeql-action/init@" in codeql
    assert "security-events: write" in codeql
    assert "ollama" not in codeql.lower()
