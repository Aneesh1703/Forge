"""
Base interface for language AST adapters.
"""

from abc import ABC, abstractmethod

from tree_sitter import Node

from app.parser.models import SymbolMetadata


class BaseLanguageAdapter(ABC):
    @abstractmethod
    def extract_symbol(
        self,
        node: Node,
        source: bytes,
    ) -> SymbolMetadata | None:
        """
        Extract language-specific symbol metadata from a Tree-sitter node.
        """
        pass
