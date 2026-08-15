"""
Script to clear all Qdrant collections.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infrastructure.qdrant import QdrantClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def clear_qdrant() -> None:
    client = QdrantClient()
    await client.connect()

    cols = await client.client.get_collections()
    if not cols.collections:
        logger.info("No collections found in Qdrant.")
    else:
        for col in cols.collections:
            await client.client.delete_collection(col.name)
            logger.info("Deleted Qdrant collection: %s", col.name)
        logger.info("All Qdrant collections cleared successfully!")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(clear_qdrant())
