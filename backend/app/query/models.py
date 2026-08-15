"""
Domain Data Transfer Objects (DTOs) for the Forge Query Engine.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.parser.models import SymbolKind
from app.parser.modifiers import Modifier
from app.parser.types import AttributeInfo, ParameterInfo
from app.parser.visibility import Visibility
from app.relationships.models import RelationshipKind, ResolutionStatus
from app.repository.language import Language


@dataclass
class SymbolQueryFilter:
    """
    Unified filter for searching code symbols across repositories.
    """

    repo_id: UUID
    name: str | None = None
    name_prefix: str | None = None
    qualified_name: str | None = None
    qualified_name_prefix: str | None = None
    kinds: set[SymbolKind] | None = None
    file_id: UUID | None = None
    language: Language | None = None
    visibility: Visibility | None = None
    modifiers: set[Modifier] | None = None
    annotation: str | None = None
    parent_symbol_id: UUID | None = None
    documentation_contains: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass
class SymbolResult:
    """
    Decoupled representation of a CodeSymbol query result.
    """

    id: UUID
    file_id: UUID
    repository_id: UUID
    name: str
    kind: SymbolKind
    language: Language
    file_path: str
    start_line: int
    end_line: int
    start_column: int
    end_column: int
    start_byte: int
    end_byte: int
    qualified_name: str | None = None
    parent_symbol_id: UUID | None = None
    parent_kind: SymbolKind | None = None
    parent_name: str | None = None
    parameters: list[ParameterInfo] = field(default_factory=list)
    return_type: str | None = None
    documentation: str | None = None
    visibility: Visibility = Visibility.UNKNOWN
    modifiers: set[Modifier] = field(default_factory=set)
    attributes: list[AttributeInfo] = field(default_factory=list)
    base_classes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipEdgeResult:
    """
    Decoupled representation of a graph relationship edge.
    """

    id: UUID
    repository_id: UUID
    file_id: UUID
    kind: RelationshipKind
    status: ResolutionStatus
    target_name: str
    source_symbol_id: UUID | None = None
    source_scope: str | None = None
    source_qualified_name: str | None = None
    source_line: int = 0
    source_column: int | None = None
    target_symbol_id: UUID | None = None
    target_module_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphTraversalResult:
    """
    Multi-hop graph traversal result containing root node, discovered nodes, and directed edges.
    """

    root_symbol_id: UUID
    max_depth: int
    nodes: dict[UUID, SymbolResult] = field(default_factory=dict)
    edges: list[RelationshipEdgeResult] = field(default_factory=list)


@dataclass
class ImpactAnalysisResult:
    """
    360-degree impact analysis result for a target symbol.
    """

    target_symbol: SymbolResult
    depth: int
    direct_callers: list[SymbolResult] = field(default_factory=list)
    indirect_callers: list[SymbolResult] = field(default_factory=list)
    dependent_types: list[SymbolResult] = field(default_factory=list)
    subclasses: list[SymbolResult] = field(default_factory=list)
    importing_file_ids: list[UUID] = field(default_factory=list)
    affected_file_paths: list[str] = field(default_factory=list)


@dataclass
class RepositoryStatisticsResult:
    """
    Repository-level summary metrics.
    """

    repository_id: UUID
    total_files: int
    total_symbols: int
    total_relationships: int
    symbols_by_kind: dict[SymbolKind, int] = field(default_factory=dict)
    files_by_language: dict[Language, int] = field(default_factory=dict)
    relationships_by_status: dict[ResolutionStatus, int] = field(default_factory=dict)
    relationships_by_kind: dict[RelationshipKind, int] = field(default_factory=dict)


@dataclass
class RepositoryContext:
    """
    Complete structural context bundle assembled for AI prompt consumption.
    """

    repository_id: UUID
    primary_symbols: list[SymbolResult] = field(default_factory=list)
    related_symbols: list[SymbolResult] = field(default_factory=list)
    relationships: list[RelationshipEdgeResult] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
