"""
OpenAIEmbeddingProvider

OpenAI text-embedding-3 provider.
"""

import os
from typing import Any

import httpx

from app.embeddings.base import BaseEmbeddingProvider


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """
    OpenAI embedding provider (text-embedding-3-small / text-embedding-3-large).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "text-embedding-3-small",
        dimension: int = 1536,
    ):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._model_name = model_name
        self._dimension = dimension
        self._api_url = "https://api.openai.com/v1/embeddings"

    @property
    def provider_name(self) -> str:
        return "openai"

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

        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable or explicit api_key parameter is required."
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model_name,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self._api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            embeddings = [item["embedding"] for item in data["data"]]
            return embeddings
