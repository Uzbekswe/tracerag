from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Environment variables use the TRAGERAG_ prefix."""

    model_config = SettingsConfigDict(env_prefix="TRAGERAG_", env_file=".env", extra="ignore")

    ollama_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    generation_model: str = "qwen3:4b"
    data_dir: Path = Path("./data")
    collection: str = "tracerag"
    top_k: int = Field(default=5, ge=1, le=50)
    # Calibrated against nomic-embed-text cosine similarities on the FastAPI demo set.
    min_retrieval_score: float = Field(default=0.72, ge=0.0, le=1.0)
    chunk_size: int = Field(default=900, ge=100, le=10000)
    chunk_overlap: int = Field(default=120, ge=0, le=2000)
    embed_batch_size: int = Field(default=128, ge=1, le=256)
    request_timeout: float = Field(default=180.0, gt=0, le=600)
    model_context: int = Field(default=4096, ge=512, le=32768)
    max_answer_tokens: int = Field(default=700, ge=64, le=4096)
    source_preview_chars: int = Field(default=300, ge=40, le=2000)

    @field_validator("ollama_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def bm25_path(self) -> Path:
        return self.data_dir / "bm25" / f"{self.collection}.json"

    @property
    def corpus_path(self) -> Path:
        return self.data_dir / "corpus"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.corpus_path.mkdir(parents=True, exist_ok=True)
