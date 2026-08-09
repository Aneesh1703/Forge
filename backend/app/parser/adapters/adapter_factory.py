"""
Responsibility

Given a Language, return the correct language adapter.

Example:

Language.PYTHON
        ↓
PythonAdapter

Language.GO
        ↓
GoAdapter

Language.RUST
        ↓
RustAdapter
"""

from app.parser.adapters.base import BaseLanguageAdapter
from app.parser.adapters.python import PythonAdapter
from app.repository.language import Language


class AdapterFactory:
    def __init__(self) -> None:
        self.cache: dict[Language, BaseLanguageAdapter] = {}
        self.hits: int = 0
        self.misses: int = 0

    def get_adapter(self, language: Language) -> BaseLanguageAdapter:
        if language in self.cache:
            self.hits += 1
            return self.cache[language]

        self.misses += 1
        if language == Language.PYTHON:
            adapter = PythonAdapter()
            self.cache[language] = adapter
            return adapter

        raise ValueError(f"Unsupported language: {language}")
