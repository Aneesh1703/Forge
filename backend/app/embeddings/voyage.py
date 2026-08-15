"""
VoyageEmbeddingProvider

Production Voyage AI embedding provider supporting voyage-code-3 with automatic
batching, inter-batch delays, and exponential backoff rate-limit handling for HTTP 429 responses.
"""

import asyncio
import logging
import os
from typing import Any

import httpx

from app.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class VoyageEmbeddingProvider(BaseEmbeddingProvider):
    """
    Voyage AI code embedding provider (voyage-code-3).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "voyage-code-3",
        dimension: int = 1024,
        batch_size: int = 32,
        inter_batch_delay: float = 0.3,
    ):
        self._api_key = api_key or os.getenv("VOYAGE_API_KEY", "")
        self._model_name = model_name
        self._dimension = dimension
        self._batch_size = batch_size
        self._inter_batch_delay = inter_batch_delay
        self._api_url = "https://api.voyageai.com/v1/embeddings"

    @property
    def provider_name(self) -> str:
        return "voyage"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_all_batches(texts, input_type="document")

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_all_batches(texts, input_type="query")

    async def _embed_all_batches(self, texts: list[str], input_type: str) -> list[list[float]]:
        if not texts:
            return []

        if not self._api_key:
            raise ValueError(
                "VOYAGE_API_KEY environment variable or explicit api_key parameter is required."
            )

        all_embeddings: list[list[float]] = []

        # Process in batches with inter-batch delay to smooth API traffic
        total_batches = (len(texts) + self._batch_size - 1) // self._batch_size
        for idx, i in enumerate(range(0, len(texts), self._batch_size), start=1):
            chunk_batch = texts[i : i + self._batch_size]
            batch_embeddings = await self._send_batch_with_retry(chunk_batch, input_type)
            all_embeddings.extend(batch_embeddings)

            if idx < total_batches and self._inter_batch_delay > 0:
                await asyncio.sleep(self._inter_batch_delay)

        return all_embeddings

    async def _send_batch_with_retry(
        self, texts: list[str], input_type: str, max_retries: int = 8
    ) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model_name,
            "input": texts,
            "input_type": input_type,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    response = await client.post(self._api_url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    return [item["embedding"] for item in data["data"]]
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429 and attempt < max_retries:
                        header_retry = float(exc.response.headers.get("retry-after", 0))
                        retry_after = max(header_retry, float(2**attempt))
                        logger.warning(
                            "Voyage AI Rate Limit (429). Retrying in %.2fs (attempt %d/%d)...",
                            retry_after,
                            attempt,
                            max_retries,
                        )
                        await asyncio.sleep(retry_after)
                    else:
                        raise
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    if attempt < max_retries:
                        wait_time = float(2**attempt)
                        logger.warning(
                            "Voyage AI Request Error (%s). Retrying in %.2fs (attempt %d/%d)...",
                            exc,
                            wait_time,
                            attempt,
                            max_retries,
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        raise

        raise RuntimeError("Failed to reach Voyage AI API after retries.")
