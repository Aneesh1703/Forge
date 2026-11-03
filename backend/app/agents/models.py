"""
AI Agent Domain Models & DTOs

Defines issue understanding payloads, candidate symbols, candidate files, and intent enums.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from app.parser.models import SymbolKind


class IssueIntent(str, Enum):
    """Classified intent of a software engineering issue or prompt."""

    BUG_FIX = "bug_fix"
    FEATURE_REQUEST = "feature_request"
    REFACTORING = "refactoring"
    PERFORMANCE = "performance"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CandidateSymbol:
    """
    Identified symbol candidate extracted from an issue description.
    """

    name: str
    qualified_name_hint: str | None = None
    kind_hint: SymbolKind | None = None
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name_hint": self.qualified_name_hint,
            "kind_hint": self.kind_hint.value if self.kind_hint else None,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class CandidateFile:
    """
    Identified target file candidate extracted from an issue description.
    """

    file_path: str
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {"file_path": self.file_path, "confidence": self.confidence}


@dataclass(frozen=True)
class IssueUnderstanding:
    """
    Structured outcome issue analysis.
    """

    issue_id: UUID
    raw_title: str
    raw_description: str
    intent: IssueIntent
    affected_symbols: list[CandidateSymbol] = field(default_factory=list)
    affected_files: list[CandidateFile] = field(default_factory=list)
    relevant_tests: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    # Explicit requests that don't fit the intent enum, e.g. "delete".
    requested_actions: list[str] = field(default_factory=list)
    # Paths the issue mentions that don't exist in the repository (never guessed).
    unresolved_paths: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        title: str,
        description: str,
        intent: IssueIntent = IssueIntent.UNKNOWN,
        symbols: list[CandidateSymbol] | None = None,
        files: list[CandidateFile] | None = None,
        tests: list[str] | None = None,
        constraints: list[str] | None = None,
        issue_id: UUID | None = None,
        requested_actions: list[str] | None = None,
        unresolved_paths: list[str] | None = None,
    ) -> "IssueUnderstanding":
        """Factory constructor for IssueUnderstanding."""
        return cls(
            issue_id=issue_id or uuid4(),
            raw_title=title.strip(),
            raw_description=description.strip(),
            intent=intent,
            affected_symbols=symbols or [],
            affected_files=files or [],
            relevant_tests=tests or [],
            constraints=constraints or [],
            requested_actions=requested_actions or [],
            unresolved_paths=unresolved_paths or [],
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for JobState and plan.json."""
        return {
            "issue_id": str(self.issue_id),
            "title": self.raw_title,
            "description": self.raw_description,
            "intent": self.intent.value,
            "affected_symbols": [s.to_dict() for s in self.affected_symbols],
            "affected_files": [f.to_dict() for f in self.affected_files],
            "relevant_tests": list(self.relevant_tests),
            "constraints": list(self.constraints),
            "requested_actions": list(self.requested_actions),
            "unresolved_paths": list(self.unresolved_paths),
        }
