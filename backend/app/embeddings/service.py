"""
EmbeddingService

Incremental embedding batch service with vendor selection, content hash skipping,
and vector metadata tagging.
"""

import os
from dataclasses import dataclass, field

from app.chunks.models import CodeChunk
from app.embeddings.base import BaseEmbeddingProvider
from app.embeddings.mock import MockEmbeddingProvider
from app.embeddings.ollama import OllamaEmbeddingProvider
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.voyage import VoyageEmbeddingProvider


@dataclass(frozen=True)
class EmbeddedChunkResult:
    """
    Immutable container wrapping a CodeChunk with its versioned vector embedding and model metadata.
    """

    chunk: CodeChunk
    vector: list[float]
    provider: str
    model: str
    dimension: int
    content_hash: str
    embedding_version: int = 1
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


class EmbeddingService:
    """
    Service managing batch embedding generation and incremental content hash skipping.
    """

    def __init__(
        self,
        provider: BaseEmbeddingProvider | None = None,
        batch_size: int = 64,
    ):
        self._provider = provider or self._resolve_provider_from_env()
        self._batch_size = batch_size

    @property
    def provider(self) -> BaseEmbeddingProvider:
        return self._provider

    async def embed_chunks(
        self,
        chunks: list[CodeChunk],
        existing_hashes: set[str] | None = None,
    ) -> list[EmbeddedChunkResult]:
        """
        Generates vector embeddings for chunks, skipping any whose
        content_hash is present in existing_hashes.
        """
        if not chunks:
            return []

        known_hashes = existing_hashes or set()

        # Incremental cost protection filter
        to_embed = [c for c in chunks if c.content_hash not in known_hashes]
        if not to_embed:
            return []

        results: list[EmbeddedChunkResult] = []

        # Batch execution
        for i in range(0, len(to_embed), self._batch_size):
            batch = to_embed[i : i + self._batch_size]
            texts = [c.content for c in batch]

            vectors = await self._provider.embed_documents(texts)

            for chunk, vec in zip(batch, vectors):
                results.append(
                    EmbeddedChunkResult(
                        chunk=chunk,
                        vector=vec,
                        provider=self._provider.provider_name,
                        model=self._provider.model_name,
                        dimension=self._provider.dimension,
                        content_hash=chunk.content_hash,
                        embedding_version=1,
                    )
                )

        return results

    async def embed_query(self, query_text: str) -> tuple[list[float], str, str, int]:
        """
        Embeds a search query string using the provider's embed_queries API.
        Returns (vector, provider_name, model_name, dimension).
        """
        vectors = await self._provider.embed_queries([query_text])
        if not vectors:
            raise ValueError("Failed to generate query embedding vector.")

        return (
            vectors[0],
            self._provider.provider_name,
            self._provider.model_name,
            self._provider.dimension,
        )

    @staticmethod
    def _resolve_provider_from_env() -> BaseEmbeddingProvider:
        provider_type = os.getenv("EMBEDDING_PROVIDER", "").lower()
        model_name = os.getenv("EMBEDDING_MODEL", "")

        if provider_type == "voyage":
            return VoyageEmbeddingProvider(
                model_name=model_name or "voyage-code-3",
                dimension=1024,
            )

        if provider_type == "openai":
            return OpenAIEmbeddingProvider(
                model_name=model_name or "text-embedding-3-small",
                dimension=1536,
            )

        if provider_type == "ollama":
            return OllamaEmbeddingProvider(
                model_name=model_name or "nomic-embed-text",
                dimension=768,
            )

        # Fallback to Mock provider for local execution & tests
        return MockEmbeddingProvider(
            model_name=model_name or "mock-embed-v1",
            dimension=128,
        )
