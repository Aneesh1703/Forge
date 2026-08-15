"""
BaseEmbeddingProvider

Abstract base class defining the provider-agnostic embedding interface.
"""

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """
    Abstract interface for code embedding providers.
    Separates document embedding (chunk indexing) from query embedding (retrieval search).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Unique provideridentifier (e.g. 'voyage', 'openai', 'ollama', 'mock').
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """
        Name of the embedding model (e.g. 'voyage-code-3', 'text-embedding-3-small').
        """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """
        Vector dimension output size (e.g. 1024, 1536, 768).
        """

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of document texts (code chunks) for indexing.
        """

    @abstractmethod
    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of query strings for similarity retrieval.
        """
