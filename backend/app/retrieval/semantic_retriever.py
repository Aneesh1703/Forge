"""
Filtered Semantic Retriever Service

Performs semantic code chunk retrieval with hierarchical level filtering,
repository scoping, and metadata score thresholds.
"""

import logging

from app.embeddings.cached_service import CachedEmbeddingService
from app.embeddings.service import EmbeddingService
from app.infrastructure.qdrant.collections import QdrantCollectionManager
from app.retrieval.models import RetrievalChunkHit, SemanticSearchRequest
from app.vector_store.base import VectorStore
from app.vector_store.models import VectorSearchQuery

logger = logging.getLogger(__name__)


class SemanticRetriever:
    """
    Retrieves semantically relevant code chunks from Qdrant vector store.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        collection_manager: QdrantCollectionManager,
        embedding_service: EmbeddingService | CachedEmbeddingService,
    ) -> None:
        self._vector_store = vector_store
        self._collection_manager = collection_manager
        self._embedding_service = embedding_service

    async def search(self, request: SemanticSearchRequest) -> list[RetrievalChunkHit]:
        """
        Execute filtered semantic search for code chunks matching the request criteria.
        """
        if not request.query_text.strip():
            return []

        # 1. Generate query vector
        (
            query_vector,
            provider,
            model,
            dimension,
        ) = await self._embedding_service.embed_query(request.query_text)

        # 2. Resolve collection name
        collection_name = self._collection_manager.get_collection_name(
            provider=provider,
            model=model,
            dimension=dimension,
        )

        # 3. Construct VectorSearchQuery criteria
        query_dto = VectorSearchQuery(
            query_vector=query_vector,
            limit=request.limit,
            repository_id=request.repository_id,
            file_id=request.file_id,
            languages=request.languages,
            chunk_types=request.chunk_types,
            levels=request.levels,
            score_threshold=request.score_threshold,
        )

        # 4. Search vector store
        results = await self._vector_store.search(collection_name, query_dto)

        # 5. Transform hits
        hits: list[RetrievalChunkHit] = []
        for hit in results:
            hits.append(
                RetrievalChunkHit(
                    chunk_id=hit.chunk_id,
                    score=hit.score,
                    level=hit.level,
                    chunk_type=hit.chunk_type,
                    file_path=hit.file_path,
                    symbol_name=hit.symbol_name or hit.metadata.get("symbol_name"),
                    qualified_name=hit.qualified_name or hit.metadata.get("qualified_name"),
                    content=hit.content,
                    metadata=hit.metadata,
                )
            )

        logger.info(
            "SemanticRetriever returned %d hits for query '%s' in repository %s",
            len(hits),
            request.query_text[:40],
            request.repository_id,
        )
        return hits
