from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from tree_sitter import Tree

from app.parser.modifiers import Modifier
from app.parser.types import AttributeInfo, ParameterInfo
from app.parser.visibility import Visibility
from app.repository.language import Language
from app.repository.models import RepositoryFile


@dataclass(frozen=True)
class ParseResult:
    tree: Tree
    source: bytes


class SymbolKind(str, Enum):
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
    name: str
    kind: SymbolKind
    parent: ParentSymbol | None = None

    parameters: list[ParameterInfo] = field(default_factory=list)
    return_type: str | None = None
    documentation: str | None = None

    visibility: Visibility = Visibility.UNKNOWN

    modifiers: set[Modifier] = field(default_factory=set)
    attributes: list[AttributeInfo] = field(default_factory=list)

    base_classes: list[str] = field(default_factory=list)

    # Language-specific information only.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeSymbol:
    # Identity
    name: str
    kind: SymbolKind
    language: Language
    file: RepositoryFile

    # Location
    start_line: int
    end_line: int
    start_column: int
    end_column: int
    start_byte: int
    end_byte: int

    # Database identity
    id: UUID = field(default_factory=uuid4)

    # Hierarchy
    qualified_name: str | None = None
    parent: ParentSymbol | None = None
    parent_symbol_id: UUID | None = None

    # Semantic information
    parameters: list[ParameterInfo] = field(default_factory=list)
    return_type: str | None = None
    documentation: str | None = None

    visibility: Visibility = Visibility.UNKNOWN

    modifiers: set[Modifier] = field(default_factory=set)
    attributes: list[AttributeInfo] = field(default_factory=list)

    base_classes: list[str] = field(default_factory=list)

    # Language-specific information only.
    metadata: dict[str, Any] = field(default_factory=dict)
