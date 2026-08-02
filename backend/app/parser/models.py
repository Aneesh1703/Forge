"""
Enum

SymbolKind

--------------------------------

Dataclass

CodeSymbol

Fields

name

kind (SymbolKind)

language (Language)

file (RepositoryFile)

start_line

end_line

start_column

end_column"""

from dataclasses import dataclass, field
from enum import Enum

from app.repository.language import Language
from app.repository.models import RepositoryFile


class SymbolKind(Enum):
    UNKNOWN = "unknown"
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    INTERFACE = "interface"
    VARIABLE = "variable"
    CONSTANT = "constant"
    TYPE = "type"
    NAMESPACE = "namespace"
    MODULE = "module"


@dataclass
class ParentSymbol:
    kind: SymbolKind
    name: str


@dataclass
class SymbolMetadata:
    kind: SymbolKind
    name: str
    parent: ParentSymbol | None = None

    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    docstring: str | None = None
    parameters: list[str] = field(default_factory=list)
    return_type: str | None = None


@dataclass
class CodeSymbol:
    name: str
    kind: SymbolKind
    language: Language
    file: RepositoryFile

    start_line: int
    end_line: int
    start_column: int
    end_column: int
    parent: ParentSymbol | None = None
