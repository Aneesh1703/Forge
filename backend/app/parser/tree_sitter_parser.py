"""
Import RepositoryFile

Import Parser
Import Language

Create TreeSitterParser

--------------------------------

Constructor

Input

Tree-sitter Language

Store

Parser

--------------------------------

Method

parse(repository_file)

Algorithm

1. Read the file contents.

2. Encode text as UTF-8 bytes.

3. Parse bytes using the parser.

4. Return the syntax tree.
"""

from tree_sitter import Parser, Tree

from app.repository.models import RepositoryFile


class TreeSitterParser:
    def __init__(self, grammar) -> None:
        self.parser = Parser()
        self.parser.language = grammar

    def parse(self, repository_file: RepositoryFile) -> Tree:
        source = repository_file.path.read_text(encoding="utf-8")
        return self.parser.parse(source.encode("utf-8"))
