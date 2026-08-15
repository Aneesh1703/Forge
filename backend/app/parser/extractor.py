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

from uuid import UUID

from tree_sitter import Node, Tree

from app.parser.adapters.base import BaseLanguageAdapter
from app.parser.models import CodeSymbol
from app.parser.position import BytePositionMapper
from app.relationships.models import RawRelationship
from app.repository.models import RepositoryFile


class SymbolExtractor:
    """
    Extract symbols and raw relationships from a Tree-sitter AST using a language adapter.
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
        symbols, _ = self.extract_with_relationships(tree, repository_file, source)
        return symbols

    def extract_with_relationships(
        self,
        tree: Tree,
        repository_file: RepositoryFile,
        source: bytes,
    ) -> tuple[list[CodeSymbol], list[RawRelationship]]:
        """
        Extract symbols and raw relationships from a Tree-sitter AST.
        """
        mapper = BytePositionMapper(source)
        symbols: list[CodeSymbol] = []
        raw_relationships: list[RawRelationship] = []
        stack: list[Node] = [tree.root_node]
        parent_stack: list[
            tuple[int, UUID, str, str | None]
        ] = []  # end_byte, symbol_id, name, qual_name

        while stack:
            node = stack.pop()

            start_byte = node.start_byte
            end_byte = node.end_byte

            while parent_stack and start_byte >= parent_stack[-1][0]:
                parent_stack.pop()

            current_parent_id = parent_stack[-1][1] if parent_stack else None
            current_symbol_name = parent_stack[-1][2] if parent_stack else None
            current_qual_name = parent_stack[-1][3] if parent_stack else None

            metadata = self.adapter.extract_symbol(node, source)
            start_line, start_column = mapper.position(start_byte)

            if metadata is not None:
                end_line, end_column = mapper.position(end_byte)

                symbol = CodeSymbol(
                    name=metadata.name,
                    kind=metadata.kind,
                    language=repository_file.language,
                    file=repository_file,
                    start_line=start_line,
                    end_line=end_line,
                    start_column=start_column,
                    end_column=end_column,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    parent=metadata.parent,
                    parent_symbol_id=current_parent_id,
                    parameters=metadata.parameters,
                    return_type=metadata.return_type,
                    documentation=metadata.documentation,
                    visibility=metadata.visibility,
                    modifiers=metadata.modifiers,
                    attributes=metadata.attributes,
                    base_classes=metadata.base_classes,
                    metadata=metadata.metadata,
                )
                symbols.append(symbol)
                parent_stack.append((end_byte, symbol.id, symbol.name, symbol.qualified_name))

            extracted_rels = self.adapter.extract_relationships(
                node=node,
                source=source,
                file_id=repository_file.id,
                start_line=start_line,
                start_column=start_column,
                current_symbol=metadata,
                scope=current_symbol_name,
                qualified_name=current_qual_name,
            )
            if extracted_rels:
                raw_relationships.extend(extracted_rels)

            # Push children in reverse so leftmost child is processed first.
            for i in range(node.child_count - 1, -1, -1):
                child = node.child(i)
                if child is not None:
                    stack.append(child)

        return symbols, raw_relationships
