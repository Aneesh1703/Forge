"""
Redis Client

Manages the async Redis connection pool, lifecycle, and health checks.
"""

import logging

import redis.asyncio as aioredis

from app.core.settings import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Async Redis client wrapper managing connection pool and lifecycle.
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.redis_url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """
        Initialize the async Redis connection pool.
        """
        if self._client is not None:
            return

        self._client = aioredis.from_url(
            self._url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        logger.info("Redis client connected to %s", self._url)

    async def disconnect(self) -> None:
        """
        Gracefully close the Redis connection pool.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Redis client disconnected.")

    @property
    def client(self) -> aioredis.Redis:
        """
        Return the underlying async Redis client.
        Raises RuntimeError if not connected.
        """
        if self._client is None:
            raise RuntimeError("Redis client is not connected. Call connect() first.")
        return self._client

    async def ping(self) -> bool:
        """
        Health check: returns True if Redis responds to PING.
        """
        try:
            return bool(await self.client.ping())
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError):
            return False

    async def info(self) -> dict[str, str]:
        """
        Return a subset of Redis server info for diagnostics.
        """
        raw: dict[str, str] = await self.client.info(section="server")
        return {
            "redis_version": raw.get("redis_version", "unknown"),
            "uptime_in_seconds": raw.get("uptime_in_seconds", "0"),
            "connected_clients": raw.get("connected_clients", "0"),
        }


# ── Module-level singleton ──────────────────────────────────────────
redis_client = RedisClient()
