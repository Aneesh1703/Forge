"""
Parser Service

Purpose

Provide a single public API for parsing a repository file.

The caller should not know about:

- Tree-sitter
- ParserFactory
- AdapterFactory
- SymbolExtractor

--------------------------------------------------

Create

ParserService

--------------------------------------------------

Constructor

Input

ParserFactory

AdapterFactory

--------------------------------------------------

Method

parse_file(repository_file)

Input

RepositoryFile

Output

list[CodeSymbol]

--------------------------------------------------

Algorithm

1. Read language from RepositoryFile.

2. Request parser from ParserFactory.

3. Parse the file.

4. Request language adapter from AdapterFactory.

5. Create SymbolExtractor using the adapter.

6. Read source bytes from the file.

7. Extract symbols from the syntax tree.

8. Return the extracted symbols.


"""

from app.parser.adapters.adapter_factory import AdapterFactory
from app.parser.extractor import SymbolExtractor
from app.parser.models import CodeSymbol
from app.parser.parser_factory import ParserFactory
from app.repository.models import RepositoryFile


class ParserService:
    """
    Service that orchestrates parsing of repository files.
    Provides a high-level API hiding tree-sitter and adapter details.
    """

    def __init__(
        self,
        parser_factory: ParserFactory = ParserFactory(),
        adapter_factory: AdapterFactory = AdapterFactory(),
    ) -> None:
        self._parser_factory = parser_factory
        self._adapter_factory = adapter_factory

    def parse_file(self, repository_file: RepositoryFile) -> list[CodeSymbol]:
        """
        Parse a single repository file and extract all code symbols.

        Args:
            repository_file: The file to parse.

        Returns:
            List of extracted code symbols.

        Raises:
            ValueError: If the language is unsupported.
            FileNotFoundError: If the file does not exist.
        """
        # 1. Get parser for the language
        parser = self._parser_factory.get_parser(repository_file.language)

        # 2. Parse the file
        result = parser.parse(repository_file)

        # 3. Get the appropriate adapter for the language
        adapter = self._adapter_factory.get_adapter(repository_file.language)

        # 4. Create extractor
        extractor = SymbolExtractor(adapter)

        # 5. Extract symbols
        symbols = extractor.extract(
            tree=result.tree,
            repository_file=repository_file,
            source=result.source,
        )

        return symbols
