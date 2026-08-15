from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class RelationshipKind(str, Enum):
    INHERITS = "inherits"
    IMPORTS = "imports"
    CALLS = "calls"
    USES_TYPE = "uses_type"
    INSTANTIATES = "instantiates"
    IMPLEMENTS = "implements"
    REFERENCES = "references"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    EXTERNAL = "external"
    UNRESOLVED = "unresolved"


@dataclass
class RawRelationship:
    source_file_id: UUID
    target_name: str
    kind: RelationshipKind
    source_line: int
    source_column: int | None = None
    source_symbol_name: str | None = None
    source_scope: str | None = None
    source_qualified_name: str | None = None
    target_module_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeRelationship:
    repository_id: UUID
    file_id: UUID
    source_line: int
    target_name: str
    kind: RelationshipKind
    status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    id: UUID = field(default_factory=uuid4)
    source_symbol_id: UUID | None = None
    source_scope: str | None = None
    source_qualified_name: str | None = None
    source_column: int | None = None
    target_symbol_id: UUID | None = None
    target_module_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
