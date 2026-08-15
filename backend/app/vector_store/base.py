"""
Abstract Vector Store Contract

Defines the pluggable VectorStore interface for vector storage, similarity search,
and lifecycle operations.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from app.chunks.models import CodeChunk
from app.vector_store.models import VectorSearchQuery, VectorSearchResult


class VectorStore(ABC):
    """
    Abstract contract for vector store operations.
    """

    @abstractmethod
    async def upsert(
        self,
        collection_name: str,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
        provider: str = "",
        model: str = "",
        dimension: int = 0,
    ) -> int:
        """
        Batch upsert CodeChunk objects and their vector embeddings into a collection.
        Returns total number of points upserted.
        """
        pass

    @abstractmethod
    async def search(
        self,
        collection_name: str,
        query: VectorSearchQuery,
    ) -> list[VectorSearchResult]:
        """
        Perform vector similarity search with optional payload filters.
        """
        pass

    @abstractmethod
    async def delete_by_ids(
        self,
        collection_name: str,
        chunk_ids: list[UUID],
    ) -> int:
        """
        Delete vector points by chunk IDs.
        """
        pass

    @abstractmethod
    async def delete_by_file(
        self,
        collection_name: str,
        file_id: UUID,
    ) -> int:
        """
        Delete all vector points belonging to a specific source file.
        """
        pass

    @abstractmethod
    async def delete_by_repository(
        self,
        collection_name: str,
        repository_id: UUID,
    ) -> int:
        """
        Delete all vector points belonging to a specific repository.
        """
        pass

    @abstractmethod
    async def count(
        self,
        collection_name: str,
        repository_id: UUID | None = None,
    ) -> int:
        """
        Count total points in a collection, optionally filtered by repository.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Return True if the underlying vector store is operational.
        """
        pass
