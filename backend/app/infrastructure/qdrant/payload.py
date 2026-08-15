"""
Qdrant Payload Builder

Converts CodeChunk DTOs to Qdrant payload dictionaries and vice-versa.
"""

from typing import Any
from uuid import UUID

from app.chunks.models import ChunkType, CodeChunk
from app.repository.language import Language


class QdrantPayloadBuilder:
    """
    Helper for transforming CodeChunk domain objects to/from Qdrant payload structures.
    """

    CHUNK_TYPE_TO_LEVEL: dict[ChunkType, int] = {
        ChunkType.SYMBOL: 1,
        ChunkType.CONTEXTUAL_SYMBOL: 2,
        ChunkType.CLASS_SUMMARY: 3,
        ChunkType.FILE_OVERVIEW: 4,
        ChunkType.GRAPH_CONTEXT: 5,
    }

    @classmethod
    def chunk_to_payload(
        cls,
        chunk: CodeChunk,
        provider: str = "",
        model: str = "",
        dimension: int = 0,
    ) -> dict[str, Any]:
        """
        Convert a CodeChunk DTO into a flat Qdrant point payload dictionary.
        """
        level = cls.CHUNK_TYPE_TO_LEVEL.get(chunk.chunk_type, 1)

        return {
            "chunk_id": str(chunk.id),
            "repository_id": str(chunk.repository_id),
            "file_id": str(chunk.file_id),
            "symbol_id": str(chunk.symbol_id) if chunk.symbol_id else None,
            "level": level,
            "chunk_type": chunk.chunk_type.value,
            "language": chunk.language.value,
            "content_hash": chunk.content_hash,
            "provider": provider,
            "model": model,
            "dimension": dimension,
            "file_path": chunk.file_path,
            "symbol_name": chunk.symbol_name,
            "qualified_name": chunk.qualified_name,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "token_estimate": chunk.token_estimate,
            "content": chunk.content,
            "metadata": chunk.metadata,
        }

    @classmethod
    def payload_to_chunk(cls, payload: dict[str, Any]) -> CodeChunk:
        """
        Reconstruct a CodeChunk domain model from a Qdrant payload dictionary.
        """
        chunk_type_val = payload.get("chunk_type", ChunkType.SYMBOL.value)
        try:
            chunk_type = ChunkType(chunk_type_val)
        except ValueError:
            chunk_type = ChunkType.SYMBOL

        lang_val = payload.get("language", Language.PYTHON.value)
        try:
            language = Language(lang_val)
        except ValueError:
            language = Language.PYTHON

        return CodeChunk(
            id=UUID(payload["chunk_id"]),
            repository_id=UUID(payload["repository_id"]),
            file_id=UUID(payload["file_id"]),
            symbol_id=UUID(payload["symbol_id"]) if payload.get("symbol_id") else None,
            chunk_type=chunk_type,
            content=payload.get("content", ""),
            content_hash=payload.get("content_hash", ""),
            symbol_name=payload.get("symbol_name"),
            qualified_name=payload.get("qualified_name"),
            language=language,
            file_path=payload.get("file_path", ""),
            start_line=int(payload.get("start_line", 1)),
            end_line=int(payload.get("end_line", 1)),
            token_estimate=int(payload.get("token_estimate", 0)),
            metadata=payload.get("metadata", {}),
        )
