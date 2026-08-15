"""
Redis Cache Service

Generic async cache operations (get, set, mget, mset, delete, exists)
built on top of RedisClient.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.infrastructure.redis.client import RedisClient

logger = logging.getLogger(__name__)


class RedisCache:
    """
    High-level async cache abstraction over a RedisClient instance.
    """

    def __init__(self, client: RedisClient) -> None:
        self._client = client

    @property
    def _redis(self) -> aioredis.Redis:
        return self._client.client

    # ── Single Key Operations ────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        """
        Get a string value by key. Returns None on cache miss.
        """
        val = await self._redis.get(key)
        return str(val) if val is not None else None

    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Set a string value with an optional TTL (seconds).
        """
        if ttl_seconds is not None:
            await self._redis.set(key, value, ex=ttl_seconds)
        else:
            await self._redis.set(key, value)

    async def delete(self, key: str) -> bool:
        """
        Delete a key. Returns True if the key existed.
        """
        result: int = await self._redis.delete(key)
        return result > 0

    async def exists(self, key: str) -> bool:
        """
        Check if a key exists.
        """
        result: int = await self._redis.exists(key)
        return result > 0

    # ── Batch Operations ─────────────────────────────────────────────

    async def mget(self, keys: list[str]) -> list[str | None]:
        """
        Get multiple values by keys. Returns list aligned with input keys.
        Missing keys return None.
        """
        if not keys:
            return []
        raw = await self._redis.mget(keys)
        return [str(v) if v is not None else None for v in raw]

    async def mset(
        self,
        mapping: dict[str, str],
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Set multiple key-value pairs.
        If ttl_seconds is provided, each key is set individually with TTL.
        Otherwise uses atomic MSET.
        """
        if not mapping:
            return

        if ttl_seconds is None:
            await self._redis.mset(mapping)
        else:
            pipe = self._redis.pipeline()
            for k, v in mapping.items():
                pipe.set(k, v, ex=ttl_seconds)
            await pipe.execute()

    # ── JSON Helpers ─────────────────────────────────────────────────

    async def get_json(self, key: str) -> Any:
        """
        Get and deserialize a JSON value. Returns None on miss.
        """
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Serialize a value to JSON and store it.
        """
        await self.set(key, json.dumps(value), ttl_seconds=ttl_seconds)

    # ── Flush ────────────────────────────────────────────────────────

    async def flush_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a glob pattern (e.g. 'forge:context:*').
        Returns the number of keys deleted.
        """
        deleted = 0
        async for key in self._redis.scan_iter(match=pattern, count=500):
            await self._redis.delete(key)
            deleted += 1
        return deleted
