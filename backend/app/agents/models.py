"""
AI Agent Domain Models & DTOs

Defines issue understanding payloads, candidate symbols, candidate files, and intent enums.
"""

from dataclasses import dataclass, field
from enum import Enum
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


@dataclass(frozen=True)
class CandidateFile:
    """
    Identified target file candidate extracted from an issue description.
    """

    file_path: str
    confidence: float = 0.5


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
        )
