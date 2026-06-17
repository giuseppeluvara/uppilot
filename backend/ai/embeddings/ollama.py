"""EmbeddingBackend locale via Ollama (§83).

Usa un modello di embedding locale (default `nomic-embed-text`, 768 dim).
Resta tutto in locale: nessun dato del corpus o delle query esce verso l'esterno.
"""
from __future__ import annotations

import httpx


class OllamaEmbeddingBackend:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, text: str) -> list[float]:
        resp = httpx.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
