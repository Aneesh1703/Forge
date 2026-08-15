"""
Cached Embedding Service

Wraps EmbeddingService with a Redis cache layer to avoid redundant
provider API calls for previously embedded content hashes.
"""

import json
import logging
from typing import Any

from app.chunks.models import CodeChunk
from app.embeddings.base import BaseEmbeddingProvider
from app.embeddings.service import EmbeddedChunkResult, EmbeddingService
from app.infrastructure.redis.cache import RedisCache
from app.infrastructure.redis.keys import RedisKeys

logger = logging.getLogger(__name__)


class CachedEmbeddingService:
    """
    Embedding service with Redis read-through caching.

    Flow:
        1. For each chunk, build the model-aware cache key.
        2. MGET all keys from Redis.
        3. HIT  → deserialize cached vector, skip provider call.
        4. MISS → delegate to EmbeddingService, store result in Redis.

    If Redis is unavailable, falls back to direct provider calls.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        cache: RedisCache,
        ttl_seconds: int | None = None,
    ) -> None:
        self._service = embedding_service
        self._cache = cache
        self._ttl = ttl_seconds

    @property
    def provider(self) -> BaseEmbeddingProvider:
        return self._service.provider

    def _cache_key(self, content_hash: str) -> str:
        """Build the model-aware Redis key for a content hash."""
        p = self._service.provider
        return RedisKeys.embedding(
            provider=p.provider_name,
            model=p.model_name,
            dimension=p.dimension,
            content_hash=content_hash,
        )

    async def embed_chunks(
        self,
        chunks: list[CodeChunk],
        existing_hashes: set[str] | None = None,
    ) -> list[EmbeddedChunkResult]:
        """
        Embed chunks with Redis caching.

        1. Filter by existing_hashes (same as base service).
        2. Check Redis for cached vectors via MGET.
        3. Only send cache-missed chunks to the provider.
        4. Store newly computed vectors back into Redis.
        """
        if not chunks:
            return []

        known = existing_hashes or set()
        to_process = [c for c in chunks if c.content_hash not in known]
        if not to_process:
            return []

        # Build cache keys for all candidate chunks
        cache_keys = [self._cache_key(c.content_hash) for c in to_process]

        # Batch Redis lookup
        try:
            cached_values = await self._cache.mget(cache_keys)
        except Exception:
            logger.warning("Redis MGET failed; falling back to provider.")
            cached_values = [None] * len(cache_keys)

        results: list[EmbeddedChunkResult] = []
        cache_misses: list[CodeChunk] = []
        p = self._service.provider

        for chunk, cached_json in zip(to_process, cached_values):
            if cached_json is not None:
                # Cache HIT → deserialize
                vector: list[float] = json.loads(cached_json)
                results.append(
                    EmbeddedChunkResult(
                        chunk=chunk,
                        vector=vector,
                        provider=p.provider_name,
                        model=p.model_name,
                        dimension=p.dimension,
                        content_hash=chunk.content_hash,
                        metadata={"cache": "hit"},
                    )
                )
            else:
                cache_misses.append(chunk)

        cache_hits = len(to_process) - len(cache_misses)
        if cache_hits > 0:
            logger.info(
                "Embedding cache: %d hits, %d misses",
                cache_hits,
                len(cache_misses),
            )

        # Delegate misses to the actual provider
        if cache_misses:
            fresh_results = await self._service.embed_chunks(cache_misses)
            results.extend(fresh_results)

            # Store new vectors in Redis
            to_cache: dict[str, str] = {}
            for r in fresh_results:
                key = self._cache_key(r.content_hash)
                to_cache[key] = json.dumps(r.vector)

            if to_cache:
                try:
                    await self._cache.mset(to_cache, ttl_seconds=self._ttl)
                except Exception:
                    logger.warning("Redis MSET failed; vectors not cached.")

        return results

    async def embed_query(
        self,
        query_text: str,
    ) -> tuple[list[float], str, str, int]:
        """
        Embed a search query. Queries are NOT cached (they are ephemeral).
        """
        return await self._service.embed_query(query_text)

    async def get_cache_stats(self, content_hashes: list[str]) -> dict[str, Any]:
        """
        Return cache hit/miss stats for a list of content hashes
        without actually embedding anything.
        """
        keys = [self._cache_key(h) for h in content_hashes]
        try:
            values = await self._cache.mget(keys)
        except Exception:
            return {"total": len(keys), "hits": 0, "misses": len(keys)}

        hits = sum(1 for v in values if v is not None)
        return {
            "total": len(keys),
            "hits": hits,
            "misses": len(keys) - hits,
            "hit_rate": round(hits / len(keys) * 100, 1) if keys else 0.0,
        }
