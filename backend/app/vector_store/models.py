"""
Vector Store Domain Models & Search DTOs

Defines query criteria, search result DTOs, and filtering abstractions for vector search.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.chunks.models import ChunkType
from app.repository.language import Language


@dataclass(frozen=True)
class VectorSearchQuery:
    """
    Query parameters and metadata filters for vector similarity search.
    """

    query_vector: list[float]
    limit: int = 10
    repository_id: UUID | None = None
    file_id: UUID | None = None
    symbol_id: UUID | None = None
    languages: list[Language] | None = None
    chunk_types: list[ChunkType] | None = None
    levels: list[int] | None = None
    path_prefix: str | None = None
    score_threshold: float | None = None


@dataclass(frozen=True)
class VectorSearchResult:
    """
    Search hit returned from vector similarity search.
    """

    chunk_id: UUID
    score: float
    repository_id: UUID
    file_id: UUID
    symbol_id: UUID | None
    level: int
    chunk_type: ChunkType
    file_path: str
    content: str
    symbol_name: str | None = None
    qualified_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
