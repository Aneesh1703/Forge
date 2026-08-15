"""
MockEmbeddingProvider

Deterministic mock embedding provider generating normalized float vectors for testing.
"""

import hashlib

from app.embeddings.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """
    Mock embedding provider producing deterministic float vectors.
    """

    def __init__(
        self,
        model_name: str = "mock-embed-v1",
        dimension: int = 128,
    ):
        self._model_name = model_name
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._generate_vector(t) for t in texts]

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return [self._generate_vector(t) for t in texts]

    def _generate_vector(self, text: str) -> list[float]:
        # Generate deterministic pseudo-random float vector normalized between -1.0 and 1.0
        seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        vec: list[float] = []
        for i in range(self._dimension):
            byte_val = seed_bytes[i % len(seed_bytes)]
            val = (byte_val / 127.5) - 1.0
            vec.append(round(val, 6))

        # Normalize vector L2 norm
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [round(x / norm, 6) for x in vec]

        return vec
