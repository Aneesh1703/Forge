"""
OllamaEmbeddingProvider

Local Ollama embedding provider for offline development (nomic-embed-text / mxbai-embed-large).
"""

import os
from typing import Any

import httpx

from app.embeddings.base import BaseEmbeddingProvider


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """
    Ollama local embedding provider.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str = "nomic-embed-text",
        dimension: int = 768,
    ):
        raw_url = base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
        self._base_url = raw_url.rstrip("/")
        self._model_name = model_name
        self._dimension = dimension
        self._api_url = f"{self._base_url}/api/embed"

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_batch(texts)

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_batch(texts)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload: dict[str, Any] = {
            "model": self._model_name,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self._api_url, json=payload)
            response.raise_for_status()
            data = response.json()
            # Ollama returns {"embeddings": [[...], [...]]}
            embeddings: list[list[float]] = data.get("embeddings", [])
            return embeddings
