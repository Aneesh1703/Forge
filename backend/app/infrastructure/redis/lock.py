"""
Redis Distributed Lock

Provides an async context manager and lock wrapper for repository indexing lock isolation.
Prevents concurrent indexing runs on the same repository across workers.
"""

import logging
from types import TracebackType
from typing import Self

import redis.asyncio as aioredis
from redis.exceptions import LockError

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.redis.keys import RedisKeys

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Raised when a distributed Redis lock cannot be acquired."""

    pass


class RedisLock:
    """
    Async distributed lock for repository indexing coordination.
    """

    def __init__(
        self,
        client: RedisClient,
        repo_id: str,
        timeout: float = 300.0,
        blocking_timeout: float | None = 5.0,
    ) -> None:
        self._client = client
        self._key = RedisKeys.index_lock(repo_id)
        self._timeout = timeout
        self._blocking_timeout = blocking_timeout
        self._lock: aioredis.lock.Lock | None = None
        self._acquired = False

    @property
    def is_acquired(self) -> bool:
        """Returns True if lock is currently held by this instance."""
        return self._acquired

    async def acquire(self) -> bool:
        """
        Attempt to acquire the distributed lock.
        Returns True if acquired, False otherwise.
        """
        if self._acquired:
            return True

        try:
            redis_inst = self._client.client
            self._lock = redis_inst.lock(
                name=self._key,
                timeout=self._timeout,
                blocking_timeout=self._blocking_timeout,
            )
            self._acquired = await self._lock.acquire()
            if self._acquired:
                logger.info("Acquired Redis lock for key: %s", self._key)
            return self._acquired
        except Exception as err:
            logger.warning("Failed to acquire Redis lock %s: %s", self._key, err)
            self._acquired = False
            return False

    async def release(self) -> None:
        """
        Release the distributed lock safely.
        """
        if not self._acquired or self._lock is None:
            return

        try:
            await self._lock.release()
            logger.info("Released Redis lock for key: %s", self._key)
        except LockError:
            logger.warning("Lock %s was already expired or released by another worker.", self._key)
        except Exception as err:
            logger.warning("Error releasing lock %s: %s", self._key, err)
        finally:
            self._acquired = False
            self._lock = None

    async def __aenter__(self) -> Self:
        acquired = await self.acquire()
        if not acquired:
            raise LockAcquisitionError(f"Could not acquire lock for {self._key}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.release()
