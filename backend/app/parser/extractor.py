"""
Create SymbolExtractor

Purpose

Convert a Tree-sitter AST into a list of generic CodeSymbol objects.

The extractor should never know anything about Python, Go, Rust,
or any other language. All language-specific logic must be delegated
to the LanguageAdapter.

------------------------------------------------------------

Constructor

Input

BaseLanguageAdapter

Algorithm

1. Store the adapter.

2. The adapter will be used to convert AST nodes
   into SymbolMetadata.

------------------------------------------------------------

Public Method

extract(
    tree,
    repository_file,
    source,
)

Returns

list[CodeSymbol]

------------------------------------------------------------

Algorithm

1. Create an empty collection.

       symbols = []

2. Get the root node.

       root = tree.root_node

3. Start recursive traversal.

       _visit(
           node=root,
           repository_file=repository_file,
           source=source,
           symbols=symbols,
       )

4. Return the collected symbols.

------------------------------------------------------------

Private Method

_visit(
    node,
    repository_file,
    source,
    symbols,
)

------------------------------------------------------------

Algorithm

1. Ask the language adapter to extract metadata
   from the current node.

       metadata =
           adapter.extract_symbol(
               node,
               source,
           )

------------------------------------------------------------

2. If metadata exists

       Create a CodeSymbol.

       Fields

       name
           metadata.name

       kind
           metadata.kind

       language
           repository_file.language

       file
           repository_file

       start_line
           node.start_point.row

       end_line
           node.end_point.row

       start_column
           node.start_point.column

       end_column
           node.end_point.column

       parent
           metadata.parent

------------------------------------------------------------

3. Append the new CodeSymbol
   to the symbols collection.

------------------------------------------------------------

4. Iterate through every child node.

       For each child

           Call

               _visit(
                   child,
                   repository_file,
                   source,
                   symbols,
               )

------------------------------------------------------------

5. Return.

------------------------------------------------------------

Overall Flow

Repository
        │
        ▼
RepositoryWalker
        │
        ▼
RepositoryFile
        │
        ▼
TreeSitterParser
        │
        ▼
Tree
        │
        ▼
SymbolExtractor
        │
        ▼
LanguageAdapter
        │
        ▼
SymbolMetadata
        │
        ▼
CodeSymbol
"""

from tree_sitter import Node, Tree

from app.parser.adapters.base import BaseLanguageAdapter
from app.parser.models import CodeSymbol
from app.repository.models import RepositoryFile


class SymbolExtractor:
    """
    Extract symbols from a Tree-sitter AST using a language adapter.
    """

    def __init__(self, adapter: BaseLanguageAdapter) -> None:
        self.adapter = adapter

    def extract(
        self,
        tree: Tree,
        repository_file: RepositoryFile,
        source: bytes,
    ) -> list[CodeSymbol]:
        """
        Extract symbol metadata from a Tree-sitter AST.
        """
        symbols: list[CodeSymbol] = []
        root = tree.root_node
        self._visit(root, repository_file, source, symbols)
        return symbols

    def _visit(
        self,
        node: Node,
        repository_file: RepositoryFile,
        source: bytes,
        symbols: list[CodeSymbol],
    ) -> None:
        """
        Recursive visitor for AST nodes.
        """
        metadata = self.adapter.extract_symbol(node, source)
        if metadata is not None:
            symbol = CodeSymbol(
                name=metadata.name,
                kind=metadata.kind,
                language=repository_file.language,
                file=repository_file,
                start_line=node.start_point.row,
                end_line=node.end_point.row,
                start_column=node.start_point.column,
                end_column=node.end_point.column,
                parent=metadata.parent,
            )
            symbols.append(symbol)
        for child in node.children:
            self._visit(child, repository_file, source, symbols)
