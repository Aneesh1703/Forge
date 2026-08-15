"""
Retrieval Domain Models & DTOs

Defines search requests, hit DTOs, and options for semantic and hybrid retrieval.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.chunks.models import ChunkType
from app.repository.language import Language


@dataclass(frozen=True)
class SemanticSearchRequest:
    """
    Search parameters for filtered semantic vector retrieval.
    """

    query_text: str
    repository_id: UUID
    limit: int = 10
    levels: list[int] | None = None
    chunk_types: list[ChunkType] | None = None
    languages: list[Language] | None = None
    file_id: UUID | None = None
    score_threshold: float | None = 0.3


@dataclass(frozen=True)
class RetrievalChunkHit:
    """
    Ranked result hit returned from semantic search.
    """

    chunk_id: UUID
    score: float
    level: int
    chunk_type: ChunkType
    file_path: str
    symbol_name: str | None
    qualified_name: str | None
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HybridContextRequest:
    """
    Parameters for fusing vector similarity hits with AST graph relationships.
    """

    query_text: str
    repository_id: UUID
    max_tokens: int = 4000
    vector_limit: int = 10
    include_graph_impact: bool = True
    levels: list[int] | None = None
    score_threshold: float | None = 0.3


@dataclass(frozen=True)
class HybridContextBundle:
    """
    Context-aware prompt bundle combining vector retrieval with graph relationships.
    """

    query_text: str
    repository_id: UUID
    vector_hits: list[RetrievalChunkHit]
    graph_context_prompt: str
    combined_context: str
    token_count_estimate: int
    referenced_file_paths: list[str] = field(default_factory=list)
