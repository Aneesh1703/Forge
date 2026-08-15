"""
Incremental Vector Indexer Plugin

Coordinates incremental Qdrant synchronization during repository indexing.
Executes vector purges for stale files and embeds/upserts new semantic chunks.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chunks.chunk_builder import SemanticChunkBuilder
from app.embeddings.cached_service import CachedEmbeddingService
from app.embeddings.service import EmbeddingService
from app.infrastructure.qdrant.collections import QdrantCollectionManager
from app.parser.models import CodeSymbol
from app.repository.models import RepositoryFile
from app.vector_store.base import VectorStore

logger = logging.getLogger(__name__)


class IncrementalVectorIndexer:
    """
    Manages incremental vector embedding and synchronization with Qdrant.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        collection_manager: QdrantCollectionManager,
        embedding_service: EmbeddingService | CachedEmbeddingService,
        db_session: AsyncSession | None = None,
        chunk_builder: SemanticChunkBuilder | None = None,
        provider: str = "ollama",
        model: str = "nomic-embed-text",
        dimension: int = 768,
    ) -> None:
        self._vector_store = vector_store
        self._collection_manager = collection_manager
        self._embedding_service = embedding_service
        self._session = db_session
        self._chunk_builder = chunk_builder
        self._provider = provider
        self._model = model
        self._dimension = dimension

    async def sync_incremental(
        self,
        repository_id: UUID,
        stale_file_ids: list[UUID],
        parsed_files: list[RepositoryFile],
        symbols: list[CodeSymbol],
    ) -> int:
        """
        1. Ensure model-aware collection exists in Qdrant.
        2. Purge Qdrant points for all stale/modified file IDs.
        3. Build semantic chunks for new/modified files using ChunkBuilder.
        4. Embed and batch upsert new chunks into Qdrant.
        """
        collection_name = await self._collection_manager.ensure_collection(
            provider=self._provider,
            model=self._model,
            dimension=self._dimension,
        )

        # 1. Purge stale file vectors
        if stale_file_ids:
            for fid in stale_file_ids:
                await self._vector_store.delete_by_file(collection_name, fid)
            logger.info("Purged Qdrant vectors for %d stale files", len(stale_file_ids))

        if not parsed_files or not symbols:
            return 0

        # 2. Build semantic chunks across levels
        if self._chunk_builder is None and self._session is not None:
            self._chunk_builder = SemanticChunkBuilder(self._session)

        if self._chunk_builder is not None:
            chunks = await self._chunk_builder.build_all_chunks_for_repository(repository_id)
        else:
            chunks = []

        if not chunks:
            return 0

        # 3. Generate embeddings via embed_chunks
        embedded_results = await self._embedding_service.embed_chunks(chunks)
        if not embedded_results:
            return 0

        chunks_to_upsert = [res.chunk for res in embedded_results]
        vectors_to_upsert = [res.vector for res in embedded_results]

        # 4. Upsert into Qdrant
        total_upserted = await self._vector_store.upsert(
            collection_name=collection_name,
            chunks=chunks_to_upsert,
            embeddings=vectors_to_upsert,
            provider=self._provider,
            model=self._model,
            dimension=self._dimension,
        )

        logger.info(
            "Incremental vector sync complete: %d chunks embedded & upserted into %s",
            total_upserted,
            collection_name,
        )
        return total_upserted

    async def delete_repository_vectors(self, repository_id: UUID) -> int:
        """
        Purge all vector points belonging to a repository from Qdrant.
        """
        collection_name = self._collection_manager.get_collection_name(
            self._provider, self._model, self._dimension
        )
        return await self._vector_store.delete_by_repository(collection_name, repository_id)
