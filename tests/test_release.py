from pathlib import Path

from tracerag import __version__


def test_package_version_is_v11() -> None:
    assert __version__ == "1.1.0"


def test_ci_pins_uv_and_runs_package_build() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'version: "0.11.15"' in workflow
    assert "uv build" in workflow
    assert "ollama" not in workflow.lower()
    assert "benchmark" not in workflow.lower()
    assert "tracerag eval" not in workflow.lower()
