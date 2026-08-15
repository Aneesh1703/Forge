"""
Qdrant Collection Manager

Manages model-aware Qdrant collection lifecycle and selective payload field indexing.
Collection format: forge_chunks_{provider}_{model}_{dimension}
"""

import logging

from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from app.infrastructure.qdrant.client import QdrantClient

logger = logging.getLogger(__name__)


class QdrantCollectionManager:
    """
    Manages Qdrant collections and payload index creation.
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    @staticmethod
    def get_collection_name(provider: str, model: str, dimension: int) -> str:
        """
        Generate standardized, model-aware collection name.
        Example: forge_chunks_voyage_voyage_code_3_1024
        """
        clean_provider = provider.lower().replace("-", "_").replace(" ", "_")
        clean_model = (
            model.lower()
            .replace("-", "_")
            .replace(" ", "_")
            .replace("/", "_")
            .replace(".", "_")
            .replace(":", "_")
        )
        return f"forge_chunks_{clean_provider}_{clean_model}_{dimension}"

    async def ensure_collection(
        self,
        provider: str,
        model: str,
        dimension: int,
    ) -> str:
        """
        Ensure model-aware collection exists in Qdrant with HNSW settings & payload indexes.
        Returns the collection name.
        """
        coll_name = self.get_collection_name(provider, model, dimension)
        qdrant = self._client.client

        collections_res = await qdrant.get_collections()
        existing_names = {c.name for c in collections_res.collections}

        if coll_name not in existing_names:
            logger.info("Creating Qdrant collection %s (dimension=%d)...", coll_name, dimension)
            await qdrant.create_collection(
                collection_name=coll_name,
                vectors_config=VectorParams(
                    size=dimension,
                    distance=Distance.COSINE,
                ),
            )
            await self._create_payload_indexes(coll_name)

        return coll_name

    async def _create_payload_indexes(self, collection_name: str) -> None:
        """
        Create selective payload indexes on frequently filtered fields.
        """
        qdrant = self._client.client

        # KEYWORD indexes
        keyword_fields = [
            "repository_id",
            "file_id",
            "symbol_id",
            "chunk_type",
            "language",
        ]
        for field in keyword_fields:
            try:
                await qdrant.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
                logger.debug("Created KEYWORD payload index for '%s' in %s", field, collection_name)
            except Exception as err:
                logger.warning("Failed to create payload index for '%s': %s", field, err)

        # INTEGER indexes
        try:
            await qdrant.create_payload_index(
                collection_name=collection_name,
                field_name="level",
                field_schema=PayloadSchemaType.INTEGER,
            )
            logger.debug("Created INTEGER payload index for 'level' in %s", collection_name)
        except Exception as err:
            logger.warning("Failed to create payload index for 'level': %s", err)
