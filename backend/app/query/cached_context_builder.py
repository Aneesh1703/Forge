"""
CachedRepositoryContextBuilder

Extends RepositoryContextBuilder with Redis read-through caching for symbol context bundles.
"""

import logging
from uuid import UUID

from app.infrastructure.redis.cache import RedisCache
from app.infrastructure.redis.keys import RedisKeys
from app.query.context_builder import RepositoryContextBuilder
from app.query.models import RepositoryContext, SymbolResult
from app.query.serializers import (
    repository_context_from_dict,
    repository_context_to_dict,
    symbol_result_from_dict,
    symbol_result_to_dict,
)

logger = logging.getLogger(__name__)


class CachedRepositoryContextBuilder:
    """
    RepositoryContextBuilder wrapper with Redis read-through caching.
    """

    def __init__(
        self,
        builder: RepositoryContextBuilder,
        cache: RedisCache,
        context_version: str = "v1",
        ttl_seconds: int = 3600,
    ):
        self._builder = builder
        self._cache = cache
        self._version = context_version
        self._ttl = ttl_seconds

    async def get_related_symbols(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> list[SymbolResult]:
        """
        Fetch related symbols with Redis read-through caching.
        """
        key = RedisKeys.query(
            repo_id="global",
            query_type="related_symbols",
            query_hash=f"{symbol_id}_d{depth}",
            context_version=self._version,
        )

        try:
            cached = await self._cache.get_json(key)
            if cached and isinstance(cached, list):
                return [symbol_result_from_dict(s) for s in cached]
        except Exception:
            logger.warning("Redis GET failed for related_symbols; falling back to DB.")

        res = await self._builder.get_related_symbols(symbol_id, depth=depth)

        try:
            serialized = [symbol_result_to_dict(s) for s in res]
            await self._cache.set_json(key, serialized, ttl_seconds=self._ttl)
        except Exception:
            logger.warning("Redis SET failed for related_symbols.")

        return res

    async def build_symbol_context(
        self,
        repo_id: UUID,
        symbol_id: UUID,
        depth: int = 1,
    ) -> RepositoryContext | None:
        """
        Build 360-degree RepositoryContext with Redis read-through caching.
        """
        key = RedisKeys.context(
            repo_id=str(repo_id),
            symbol_id=f"{symbol_id}_d{depth}",
            context_version=self._version,
        )

        try:
            cached = await self._cache.get_json(key)
            if cached and isinstance(cached, dict):
                return repository_context_from_dict(cached)
        except Exception:
            logger.warning("Redis GET failed for symbol context; falling back to DB.")

        ctx = await self._builder.build_symbol_context(repo_id, symbol_id, depth=depth)
        if ctx is None:
            return None

        try:
            serialized = repository_context_to_dict(ctx)
            await self._cache.set_json(key, serialized, ttl_seconds=self._ttl)
        except Exception:
            logger.warning("Redis SET failed for symbol context.")

        return ctx

    async def invalidate_repo_context(self, repo_id: UUID) -> None:
        """
        Invalidate all cached context bundles for a repository when re-indexed.
        """
        pattern = f"forge:context:{repo_id}:*"
        try:
            flushed = await self._cache.flush_pattern(pattern)
            logger.info("Invalidated %d cached context items for repo %s", flushed, repo_id)
        except Exception:
            logger.warning("Failed to invalidate repo context cache for %s", repo_id)
