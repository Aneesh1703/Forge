"""
Implementation Plan Domain Models

Defines FileActionType, FileAction, PlanTask, and ImplementationPlan.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum


class FileActionType(str, Enum):
    """Target action type for a file in an implementation plan."""

    MODIFY = "MODIFY"
    CREATE = "CREATE"
    DELETE = "DELETE"


@dataclass(frozen=True)
class FileAction:
    """
    Specific action targeting a file in the repository.
    """

    action_type: FileActionType
    file_path: str
    target_symbols: list[str] = field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None
    description: str = ""


@dataclass(frozen=True)
class PlanTask:
    """
    Sequential step task in an implementation plan.
    """

    step_number: int
    title: str
    description: str
    target_file: str


@dataclass
class ImplementationPlan:
    """
    Structured outcome of evidence-driven planning.
    """

    plan_id: uuid.UUID
    repository_id: uuid.UUID
    summary: str
    file_actions: list[FileAction] = field(default_factory=list)
    tasks: list[PlanTask] = field(default_factory=list)
    verification_commands: list[str] = field(default_factory=list)
    evidence_graph_id: uuid.UUID | None = None
    confidence_score: float = 0.0
    tokens_used: int = 0

    @classmethod
    def create(
        cls,
        repository_id: uuid.UUID,
        summary: str,
        file_actions: list[FileAction] | None = None,
        tasks: list[PlanTask] | None = None,
        verification_commands: list[str] | None = None,
        confidence_score: float = 0.0,
        evidence_graph_id: uuid.UUID | None = None,
        tokens_used: int = 0,
    ) -> "ImplementationPlan":
        return cls(
            plan_id=uuid.uuid4(),
            repository_id=repository_id,
            summary=summary.strip(),
            file_actions=file_actions or [],
            tasks=tasks or [],
            verification_commands=verification_commands or ["pytest"],
            evidence_graph_id=evidence_graph_id,
            confidence_score=confidence_score,
            tokens_used=tokens_used,
        )
