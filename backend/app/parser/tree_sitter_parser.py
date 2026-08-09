from tree_sitter import Language, Parser

from app.parser.models import ParseResult
from app.repository.models import RepositoryFile


class TreeSitterParser:
    def __init__(self, grammar: Language) -> None:
        self._grammar = grammar

    def parse(self, repository_file: RepositoryFile) -> ParseResult:
        source_bytes = repository_file.path.read_bytes()
        parser = Parser(self._grammar)
        tree = parser.parse(source_bytes)
        return ParseResult(tree=tree, source=source_bytes)
