"""
Chunk Domain Models

Defines retrievable code unit DTOs, chunk classifications, and content hashing functions.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID

from app.repository.language import Language


class ChunkType(str, Enum):
    """
    Hierarchical classifications for semantic code chunks.
    """

    SYMBOL = "symbol"
    CONTEXTUAL_SYMBOL = "contextual_symbol"
    CLASS_SUMMARY = "class_summary"
    FILE_OVERVIEW = "file_overview"
    GRAPH_CONTEXT = "graph_context"


def compute_content_hash(content: str) -> str:
    """
    Computes a deterministic SHA-256 hash string for chunk content and header text.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CodeChunk:
    """
    Immutable representation of a retrievable semantic chunk for vector embedding.
    """

    repository_id: UUID
    file_id: UUID
    chunk_type: ChunkType
    content: str
    content_hash: str
    id: UUID = field(default_factory=uuid.uuid4)
    symbol_id: UUID | None = None
    symbol_name: str | None = None
    qualified_name: str | None = None
    language: Language = Language.PYTHON
    file_path: str = ""
    start_line: int = 1
    end_line: int = 1
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        repository_id: UUID,
        file_id: UUID,
        chunk_type: ChunkType,
        content: str,
        symbol_id: UUID | None = None,
        symbol_name: str | None = None,
        qualified_name: str | None = None,
        language: Language = Language.PYTHON,
        file_path: str = "",
        start_line: int = 1,
        end_line: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> "CodeChunk":
        """
        Factory method automatically computing SHA-256 content_hash and token_estimate.
        """
        chash = compute_content_hash(content)
        # Approximate token count (~4 characters per token heuristic)
        token_count = max(1, len(content) // 4)
        return cls(
            id=uuid.uuid4(),
            repository_id=repository_id,
            file_id=file_id,
            symbol_id=symbol_id,
            chunk_type=chunk_type,
            content=content,
            content_hash=chash,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
            language=language,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            token_estimate=token_count,
            metadata=metadata or {},
        )
