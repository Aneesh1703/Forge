"""
Qdrant Vector Store Implementation

Provides production-grade Qdrant VectorStore implementation supporting batch upserts,
point ID idempotency, payload-filtered similarity search, and deletion primitives.
"""

import logging
from uuid import UUID

from qdrant_client.models import (
    Condition,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointIdsList,
    PointStruct,
)

from app.chunks.models import ChunkType, CodeChunk
from app.infrastructure.qdrant.client import QdrantClient
from app.infrastructure.qdrant.payload import QdrantPayloadBuilder
from app.vector_store.base import VectorStore
from app.vector_store.models import VectorSearchQuery, VectorSearchResult

logger = logging.getLogger(__name__)


class QdrantVectorStore(VectorStore):
    """
    Qdrant implementation of the VectorStore contract.
    """

    BATCH_SIZE = 500

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

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
        Batch upsert CodeChunk objects and vector embeddings using CodeChunk.id as point ID.
        """
        if not chunks or not embeddings:
            return 0

        if len(chunks) != len(embeddings):
            raise ValueError("Chunks count must match embeddings count.")

        qdrant = self._client.client
        total = 0

        for i in range(0, len(chunks), self.BATCH_SIZE):
            batch_chunks = chunks[i : i + self.BATCH_SIZE]
            batch_embeddings = embeddings[i : i + self.BATCH_SIZE]

            points: list[PointStruct] = []
            for chunk, emb in zip(batch_chunks, batch_embeddings, strict=True):
                payload = QdrantPayloadBuilder.chunk_to_payload(
                    chunk, provider=provider, model=model, dimension=dimension
                )
                points.append(
                    PointStruct(
                        id=str(chunk.id),
                        vector=emb,
                        payload=payload,
                    )
                )

            await qdrant.upsert(
                collection_name=collection_name,
                points=points,
            )
            total += len(points)

        logger.info("Upserted %d points into Qdrant collection %s", total, collection_name)
        return total

    async def search(
        self,
        collection_name: str,
        query: VectorSearchQuery,
    ) -> list[VectorSearchResult]:
        """
        Perform vector similarity search with optional payload filters.
        """
        qdrant = self._client.client
        conditions: list[Condition] = []

        if query.repository_id:
            conditions.append(
                FieldCondition(
                    key="repository_id",
                    match=MatchValue(value=str(query.repository_id)),
                )
            )
        if query.file_id:
            conditions.append(
                FieldCondition(
                    key="file_id",
                    match=MatchValue(value=str(query.file_id)),
                )
            )
        if query.symbol_id:
            conditions.append(
                FieldCondition(
                    key="symbol_id",
                    match=MatchValue(value=str(query.symbol_id)),
                )
            )
        if query.languages:
            conditions.append(
                FieldCondition(
                    key="language",
                    match=MatchAny(any=[lang.value for lang in query.languages]),
                )
            )
        if query.chunk_types:
            conditions.append(
                FieldCondition(
                    key="chunk_type",
                    match=MatchAny(any=[c.value for c in query.chunk_types]),
                )
            )
        if query.levels:
            conditions.append(
                FieldCondition(
                    key="level",
                    match=MatchAny(any=query.levels),
                )
            )

        filter_obj = Filter(must=conditions) if conditions else None

        query_res = await qdrant.query_points(
            collection_name=collection_name,
            query=query.query_vector,
            limit=query.limit,
            query_filter=filter_obj,
            score_threshold=query.score_threshold,
        )

        results: list[VectorSearchResult] = []
        for hit in query_res.points:
            payload = hit.payload or {}
            chunk_type_val = payload.get("chunk_type", ChunkType.SYMBOL.value)
            try:
                chunk_type = ChunkType(chunk_type_val)
            except ValueError:
                chunk_type = ChunkType.SYMBOL

            results.append(
                VectorSearchResult(
                    chunk_id=UUID(str(payload.get("chunk_id", hit.id))),
                    score=float(hit.score),
                    repository_id=UUID(str(payload["repository_id"])),
                    file_id=UUID(str(payload["file_id"])),
                    symbol_id=UUID(str(payload["symbol_id"])) if payload.get("symbol_id") else None,
                    level=int(payload.get("level", 1)),
                    chunk_type=chunk_type,
                    file_path=str(payload.get("file_path", "")),
                    content=str(payload.get("content", "")),
                    symbol_name=payload.get("symbol_name"),
                    qualified_name=payload.get("qualified_name"),
                    metadata=dict(payload.get("metadata", {})),
                )
            )

        return results

    async def delete_by_ids(
        self,
        collection_name: str,
        chunk_ids: list[UUID],
    ) -> int:
        """
        Delete points by chunk IDs.
        """
        if not chunk_ids:
            return 0

        qdrant = self._client.client
        point_ids: list[int | str | UUID] = [str(cid) for cid in chunk_ids]
        await qdrant.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=point_ids),
        )
        return len(chunk_ids)

    async def delete_by_file(
        self,
        collection_name: str,
        file_id: UUID,
    ) -> int:
        """
        Delete points belonging to a file via file_id payload filter.
        """
        qdrant = self._client.client
        filter_obj = Filter(
            must=[
                FieldCondition(
                    key="file_id",
                    match=MatchValue(value=str(file_id)),
                )
            ]
        )
        await qdrant.delete(
            collection_name=collection_name,
            points_selector=filter_obj,
        )
        return 1

    async def delete_by_repository(
        self,
        collection_name: str,
        repository_id: UUID,
    ) -> int:
        """
        Delete points belonging to a repository via repository_id payload filter.
        """
        qdrant = self._client.client
        filter_obj = Filter(
            must=[
                FieldCondition(
                    key="repository_id",
                    match=MatchValue(value=str(repository_id)),
                )
            ]
        )
        await qdrant.delete(
            collection_name=collection_name,
            points_selector=filter_obj,
        )
        return 1

    async def count(
        self,
        collection_name: str,
        repository_id: UUID | None = None,
    ) -> int:
        """
        Count points in collection, optionally filtered by repository_id.
        """
        qdrant = self._client.client
        filter_obj = None
        if repository_id:
            filter_obj = Filter(
                must=[
                    FieldCondition(
                        key="repository_id",
                        match=MatchValue(value=str(repository_id)),
                    )
                ]
            )

        res = await qdrant.count(
            collection_name=collection_name,
            count_filter=filter_obj,
            exact=True,
        )
        return res.count

    async def health_check(self) -> bool:
        """
        Check if Qdrant vector store is responsive.
        """
        return await self._client.ping()
