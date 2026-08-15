"""
Qdrant Infrastructure Client

Manages the AsyncQdrantClient lifecycle, connection pool, and health checks.
"""

import logging

from qdrant_client import AsyncQdrantClient

from app.core.settings import settings

logger = logging.getLogger(__name__)


class QdrantClient:
    """
    Async Qdrant client wrapper managing connection pool and lifecycle.
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.qdrant_url
        self._client: AsyncQdrantClient | None = None

    async def connect(self) -> None:
        """
        Initialize the AsyncQdrantClient.
        """
        if self._client is not None:
            return

        self._client = AsyncQdrantClient(url=self._url)
        logger.info("AsyncQdrantClient connected to %s", self._url)

    async def disconnect(self) -> None:
        """
        Gracefully close the AsyncQdrantClient connection pool.
        """
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.info("AsyncQdrantClient disconnected.")

    @property
    def client(self) -> AsyncQdrantClient:
        """
        Return the underlying AsyncQdrantClient.
        Raises RuntimeError if not connected.
        """
        if self._client is None:
            raise RuntimeError("Qdrant client is not connected. Call connect() first.")
        return self._client

    async def ping(self) -> bool:
        """
        Health check: returns True if Qdrant responds to API calls.
        """
        try:
            res = await self.client.get_collections()
            return res is not None
        except Exception as err:
            logger.warning("Qdrant health check failed: %s", err)
            return False

    async def info(self) -> dict[str, str]:
        """
        Return Qdrant server version and collection metrics for diagnostics.
        """
        try:
            collections_res = await self.client.get_collections()
            count = len(collections_res.collections) if collections_res else 0
            return {
                "qdrant_url": self._url,
                "collection_count": str(count),
                "status": "connected",
            }
        except Exception:
            return {
                "qdrant_url": self._url,
                "collection_count": "0",
                "status": "disconnected",
            }


# Module-level singleton
qdrant_client = QdrantClient()
