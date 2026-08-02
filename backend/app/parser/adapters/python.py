"""Create PythonAdapter

Inherit BaseLanguageAdapter

--------------------------------------------------

Create NODE_KIND_MAP

"class_definition"
        ↓
CLASS

"function_definition"
        ↓
FUNCTION

--------------------------------------------------

Method

extract_symbol(node, source)

Input

Tree-sitter Node

Source bytes

--------------------------------------------------

Algorithm

1. Look up node.type in NODE_KIND_MAP.

2. If node type is not supported

       return None

3. Determine symbol kind.

4. If symbol is a function

       Check parents.

       If parent is a class

            Change kind to METHOD.

5. Locate the "name" child node.

6. Read symbol name from source.

7. Find enclosing parent symbol
       (class/function/module if applicable).

8. Create SymbolMetadata

9. Return SymbolMetadata."""

from types import MappingProxyType

from tree_sitter import Node

from app.parser.adapters.base import BaseLanguageAdapter
from app.parser.models import (
    ParentSymbol,
    SymbolKind,
    SymbolMetadata,
)


class PythonAdapter(BaseLanguageAdapter):
    """
    Language adapter for Python Tree-sitter AST nodes.

    Responsible for converting Python-specific AST nodes into
    generic SymbolMetadata objects understood by Forge.
    """

    NODE_KIND_MAP = MappingProxyType(
        {
            "class_definition": SymbolKind.CLASS,
            "function_definition": SymbolKind.FUNCTION,
        }
    )

    def extract_symbol(
        self,
        node: Node,
        source: bytes,
    ) -> SymbolMetadata | None:
        """
        Extract symbol metadata from a Python AST node.

        Returns None if the node does not represent a supported symbol.
        """

        symbol_kind = self.NODE_KIND_MAP.get(node.type)

        if symbol_kind is None:
            return None

        parent = self._find_parent(node, source)

        # Functions defined inside classes are methods.
        if (
            symbol_kind == SymbolKind.FUNCTION
            and parent is not None
            and parent.kind == SymbolKind.CLASS
        ):
            symbol_kind = SymbolKind.METHOD

        name = self._extract_name(node, source)

        if not name:
            return None

        return SymbolMetadata(
            kind=symbol_kind,
            name=name,
            parent=parent,
        )

    def _extract_name(
        self,
        node: Node,
        source: bytes,
    ) -> str:
        """
        Extract the identifier name from a symbol node.
        """

        name_node = node.child_by_field_name("name")

        if name_node is None:
            return ""

        return source[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()

    def _find_parent(
        self,
        node: Node,
        source: bytes,
    ) -> ParentSymbol | None:
        """
        Find the nearest enclosing symbol.
        """

        parent = node.parent

        while parent is not None:
            if parent.type == "class_definition":
                return ParentSymbol(
                    kind=SymbolKind.CLASS,
                    name=self._extract_name(parent, source),
                )

            if parent.type == "function_definition":
                return ParentSymbol(
                    kind=SymbolKind.FUNCTION,
                    name=self._extract_name(parent, source),
                )

            parent = parent.parent

        return None
