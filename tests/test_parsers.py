from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.errors import PdfReadError

from tracerag.parsers import ScannedPdfError, parse_markdown, parse_pdf


def test_markdown_preserves_heading_breadcrumb_and_stable_ids(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text(
        "# Install\n\nRun the command.\n\n## Verify\n\nCheck the output.", encoding="utf-8"
    )
    first = parse_markdown(path, 900, 20)
    second = parse_markdown(path, 900, 20)
    assert first == second
    assert {chunk.heading_path for chunk in first} == {"Install", "Install > Verify"}
    assert first[0].chunk_type == "markdown"


def test_markdown_splits_large_content(tmp_path: Path) -> None:
    path = tmp_path / "large.md"
    path.write_text("# Section\n\n" + ("word " * 300), encoding="utf-8")
    chunks = parse_markdown(path, 200, 20)
    assert len(chunks) > 1
    assert all(chunk.heading_path == "Section" for chunk in chunks)


def test_markdown_removes_presentation_markup(tmp_path: Path) -> None:
    path = tmp_path / "markup.md"
    path.write_text(
        "# Guide\n\n<style>.hidden { display: none }</style>\n\n"
        "<p>Useful documentation about the API.</p>",
        encoding="utf-8",
    )

    chunks = parse_markdown(path, 900, 20)

    assert "display: none" not in chunks[0].text
    assert "Useful documentation" in chunks[0].text


def test_pdf_without_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(PdfReadError):
        parse_pdf(path, 900, 20)


def test_scanned_pdf_error_type_is_public() -> None:
    assert issubclass(ScannedPdfError, ValueError)


def test_textless_pdf_is_reported_as_scanned(tmp_path: Path) -> None:
    path = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(ScannedPdfError, match="scanned PDFs are unsupported"):
        parse_pdf(path, 900, 20)
