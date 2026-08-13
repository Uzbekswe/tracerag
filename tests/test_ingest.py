from pathlib import Path

from tracerag.config import Settings
from tracerag.ingest import Ingestor
from tracerag.models import Chunk


class FakeVectors:
    def __init__(self) -> None:
        self.replacements = []

    def replace_source(self, source, chunks, embeddings) -> None:
        self.replacements.append((source, chunks, embeddings))

    def all_chunks(self):
        return [chunk for _, chunks, _ in self.replacements for chunk in chunks]


class FakeLexical:
    def save(self, chunks) -> None:
        self.chunks = chunks


class FakeOllama:
    def __init__(self) -> None:
        self.calls = []

    def embed(self, model, texts):
        self.calls.append(texts)
        return [[float(len(text))] for text in texts]


def test_ingest_batches_large_source(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "large.md"
    source.write_text("# Heading\n\n" + ("word " * 25000), encoding="utf-8")
    chunks = [
        Chunk(str(index), "chunk", str(source), index, "Heading", "hash") for index in range(70)
    ]
    monkeypatch.setattr(
        "tracerag.ingest.parse_document",
        lambda *_args, **_kwargs: chunks,
    )
    ollama = FakeOllama()
    vectors = FakeVectors()
    ingestor = Ingestor(
        Settings(data_dir=tmp_path, embed_batch_size=32), vectors, FakeLexical(), ollama
    )

    processed, count = ingestor.ingest(source)

    assert (processed, count) == (1, 70)
    assert [len(call) for call in ollama.calls] == [32, 32, 6]
