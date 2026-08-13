from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path

from pypdf import PdfReader

from .models import Chunk

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HTML_BLOCK = re.compile(r"<(script|style).*?>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


class UnsupportedDocumentError(ValueError):
    """The file is outside v1's supported text/Markdown/PDF boundary."""


class ScannedPdfError(ValueError):
    """The PDF has no usable embedded text; OCR is intentionally deferred."""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + size // 2:
                end = boundary + (2 if text[boundary : boundary + 2] == ". " else 0)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return pieces


def _clean_markdown(raw: str) -> str:
    """Remove presentation markup that otherwise pollutes semantic retrieval."""
    cleaned = _HTML_BLOCK.sub("\n", raw)
    cleaned = _HTML_COMMENT.sub("\n", cleaned)
    cleaned = _HTML_TAG.sub(" ", cleaned)
    cleaned = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", cleaned, flags=re.DOTALL)
    return html.unescape(cleaned)


def parse_markdown(path: Path, size: int, overlap: int, corpus_sha: str = "") -> list[Chunk]:
    raw = _clean_markdown(path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    sections: list[tuple[str, list[str]]] = []
    heading: list[str] = []
    buffer: list[str] = []
    for line in raw.splitlines():
        match = _HEADING.match(line)
        if match:
            if buffer:
                sections.append((" > ".join(heading), buffer))
                buffer = []
            level = len(match.group(1))
            heading = heading[: level - 1] + [match.group(2).strip()]
        else:
            buffer.append(line)
    if buffer:
        sections.append((" > ".join(heading), buffer))

    chunks: list[Chunk] = []
    index = 0
    for section_heading, lines in sections:
        for piece in _split_text("\n".join(lines), size, overlap):
            digest = _hash(f"{path.resolve()}|{index}|{piece}")
            chunks.append(
                Chunk(
                    digest[:24],
                    piece,
                    str(path.resolve()),
                    index,
                    section_heading,
                    _hash(piece),
                    corpus_sha,
                    "markdown",
                    source_hash,
                )
            )
            index += 1
    return chunks


def parse_pdf(path: Path, size: int, overlap: int, corpus_sha: str = "") -> list[Chunk]:
    reader = PdfReader(str(path))
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(page for page in pages if page)
    if len(text.strip()) < 40:
        raise ScannedPdfError(
            f"{path} has no usable embedded text; scanned PDFs are unsupported in v1"
        )
    return [
        Chunk(
            _hash(f"{path.resolve()}|{i}|{piece}")[:24],
            piece,
            str(path.resolve()),
            i,
            f"Page {i + 1}",
            _hash(piece),
            corpus_sha,
            "pdf",
            source_hash,
        )
        for i, piece in enumerate(_split_text(text, size, overlap))
    ]


def parse_document(path: Path, size: int, overlap: int, corpus_sha: str = "") -> list[Chunk]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedDocumentError(
            f"Unsupported extension {suffix!r}; use Markdown, text, or PDF"
        )
    if suffix in {".md", ".markdown", ".txt"}:
        return parse_markdown(path, size, overlap, corpus_sha)
    return parse_pdf(path, size, overlap, corpus_sha)
