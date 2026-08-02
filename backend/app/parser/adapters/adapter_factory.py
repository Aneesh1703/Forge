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
    def get_adapter(self, language: "Language") -> BaseLanguageAdapter:
        if language == Language.PYTHON:
            return PythonAdapter()
        raise ValueError(f"Unsupported language: {language}")
