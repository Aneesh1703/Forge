"""
CachedGraphQueryService

Wraps GraphQueryService with Redis read-through caching for expensive callers, callees,
and graph traversal operations.
"""

import logging
from uuid import UUID

from app.infrastructure.redis.cache import RedisCache
from app.infrastructure.redis.keys import RedisKeys
from app.query.graph_query_service import GraphQueryService
from app.query.models import GraphTraversalResult
from app.query.serializers import (
    graph_traversal_from_dict,
    graph_traversal_to_dict,
)

logger = logging.getLogger(__name__)


class CachedGraphQueryService:
    """
    GraphQueryService wrapper with Redis read-through caching.
    """

    def __init__(
        self,
        service: GraphQueryService,
        cache: RedisCache,
        context_version: str = "v1",
        ttl_seconds: int = 3600,
    ):
        self._service = service
        self._cache = cache
        self._version = context_version
        self._ttl = ttl_seconds

    async def get_callers(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> GraphTraversalResult:
        """Fetch incoming callers with Redis caching."""
        return await self._cached_traversal("callers", symbol_id, depth)

    async def get_callees(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> GraphTraversalResult:
        """Fetch outgoing callees with Redis caching."""
        return await self._cached_traversal("callees", symbol_id, depth)

    async def _cached_traversal(
        self,
        query_type: str,
        symbol_id: UUID,
        depth: int,
    ) -> GraphTraversalResult:
        key = RedisKeys.query(
            repo_id="global",
            query_type=query_type,
            query_hash=f"{symbol_id}_d{depth}",
            context_version=self._version,
        )

        try:
            cached = await self._cache.get_json(key)
            if cached and isinstance(cached, dict):
                return graph_traversal_from_dict(cached)
        except Exception:
            logger.warning("Redis GET failed for graph traversal %s", query_type)

        if query_type == "callers":
            res = await self._service.get_callers(symbol_id, depth=depth)
        elif query_type == "callees":
            res = await self._service.get_callees(symbol_id, depth=depth)
        else:
            raise ValueError(f"Unsupported query type: {query_type}")

        try:
            serialized = graph_traversal_to_dict(res)
            await self._cache.set_json(key, serialized, ttl_seconds=self._ttl)
        except Exception:
            logger.warning("Redis SET failed for graph traversal %s", query_type)

        return res
