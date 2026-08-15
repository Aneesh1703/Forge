"""
Import

Language

TreeSitterParser

get_language()

-----------------------------------

Create ParserFactory

-----------------------------------

Create cache

Language

↓

TreeSitterParser

-----------------------------------

Create LANGUAGE_MAP

Language.PYTHON

↓

"python"

Language.GO

↓

"go"

...

-----------------------------------

Method

get_parser(language)

Algorithm

1. Check cache.

2. If parser exists

       return parser.

3. Convert Language enum to grammar name.

4. Load grammar.

5. Create TreeSitterParser.

6. Store parser in cache.

7. Return parser.
"""

from typing import Any

from tree_sitter_language_pack import get_language

from app.parser.tree_sitter_parser import TreeSitterParser
from app.repository.language import Language


class ParserFactory:
    LANGUAGE_MAP: dict[Language, str] = {
        Language.PYTHON: "python",
        Language.GO: "go",
        Language.RUST: "rust",
        Language.JAVA: "java",
        Language.CPP: "cpp",
        Language.C: "c",
        Language.CSHARP: "csharp",
        Language.KOTLIN: "kotlin",
        Language.SWIFT: "swift",
        Language.PHP: "php",
        Language.RUBY: "ruby",
    }

    def __init__(self) -> None:
        self.grammar_cache: dict[Language, Any] = {}
        self.hits: int = 0
        self.misses: int = 0

    def get_parser(self, language: Language) -> TreeSitterParser:
        if language in self.grammar_cache:
            self.hits += 1
            grammar = self.grammar_cache[language]
        else:
            self.misses += 1
            grammar_name = self.LANGUAGE_MAP.get(language)
            if grammar_name is None:
                raise ValueError(f"Unsupported language: {language}")

            grammar = get_language(grammar_name)
            self.grammar_cache[language] = grammar

        return TreeSitterParser(grammar)
