from __future__ import annotations

import time
from collections.abc import Iterable

import httpx


class OllamaError(RuntimeError):
    """Ollama is unavailable or returned an invalid response."""


class OllamaClient:
    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def tags(self) -> list[str]:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=10)
            response.raise_for_status()
            return [str(model.get("name", "")) for model in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OllamaError(f"Ollama is unavailable at {self.base_url}: {exc}") from exc

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": model, "input": texts, "keep_alive": "2h"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            embeddings = response.json().get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                raise OllamaError("Ollama returned an unexpected embedding count")
            return [[float(value) for value in vector] for vector in embeddings]
        except OllamaError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].strip()
            suffix = f": {detail}" if detail else ""
            raise OllamaError(
                f"Embedding request failed ({exc.response.status_code}){suffix}"
            ) from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise OllamaError(f"Embedding request failed: {exc}") from exc

    def chat(
        self, model: str, prompt: str, max_tokens: int, context_size: int = 2048
    ) -> tuple[str, float]:
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    # Long local evaluations should not let Ollama unload the
                    # generation model between cases.
                    "keep_alive": "2h",
                    # Keep Qwen3's private reasoning separate from the user-visible answer.
                    "think": True,
                    "options": {
                        "num_predict": max_tokens,
                        "num_ctx": context_size,
                        "temperature": 0,
                    },
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
            if not isinstance(content, str):
                raise OllamaError("Ollama returned no text answer")
            return content.strip(), (time.perf_counter() - started) * 1000
        except OllamaError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].strip()
            suffix = f": {detail}" if detail else ""
            raise OllamaError(
                f"Generation request failed ({exc.response.status_code}){suffix}"
            ) from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise OllamaError(f"Generation request failed: {exc}") from exc


def model_matches(installed: Iterable[str], requested: str) -> bool:
    requested = requested.lower()
    return any(
        name.lower() == requested or name.lower().split(":")[0] == requested for name in installed
    )
