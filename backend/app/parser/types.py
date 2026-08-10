from dataclasses import dataclass, field
from enum import Enum


class ParameterKind(str, Enum):
    UNKNOWN = "unknown"
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


@dataclass
class ParameterInfo:
    name: str
    kind: ParameterKind = ParameterKind.UNKNOWN
    type_annotation: str | None = None
    default_value: str | None = None


@dataclass
class AttributeInfo:
    name: str
    arguments: list[str] = field(default_factory=list)
