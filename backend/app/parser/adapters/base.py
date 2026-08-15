"""
Base interface for language AST adapters.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from tree_sitter import Node

from app.parser.models import SymbolMetadata
from app.relationships.models import RawRelationship


class BaseLanguageAdapter(ABC):
    @abstractmethod
    def extract_symbol(
        self,
        node: Node,
        source: bytes,
    ) -> SymbolMetadata | None:
        """
        Extract language-specific symbol metadata from a Tree-sitter node.

        Returns:
            SymbolMetadata when the node represents a supported symbol,
            otherwise None.
        """
        pass

    def extract_relationships(
        self,
        node: Node,
        source: bytes,
        file_id: UUID,
        start_line: int = 1,
        start_column: int = 0,
        current_symbol: SymbolMetadata | None = None,
        scope: str | None = None,
        qualified_name: str | None = None,
    ) -> list[RawRelationship]:
        """
        Extract relationships (e.g. CALLS, IMPORTS, INHERITS) from an AST node.

        Returns:
            List of RawRelationship instances extracted from this node.
        """
        return []
