"""
Phase 10A: Persistent JobState Model for Pipeline Recovery and Auditability
"""

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.agents.coder.models import ExecutionPolicy


class JobStatus(str, Enum):
    """Pipeline execution state taxonomy."""

    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    AWAITING_GATE_1 = "AWAITING_GATE_1"
    PATCHING = "PATCHING"
    TESTING = "TESTING"
    REPAIRING = "REPAIRING"
    REVIEWING = "REVIEWING"
    AWAITING_GATE_2 = "AWAITING_GATE_2"
    AWAITING_GATE_3 = "AWAITING_GATE_3"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


def _json_serializer(obj: Any) -> Any:
    if isinstance(obj, (uuid.UUID, Path)):
        return str(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


@dataclass
class JobState:
    """Persistent, serializable state representation of a Forge execution job."""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    repository_path: str = ""
    issue_prompt: str = ""
    execution_policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS
    status: JobStatus = JobStatus.PENDING

    # Step Execution Artifacts & Contexts
    issue_understanding: dict[str, Any] | None = None
    evidence_context: str | None = None
    implementation_plan: dict[str, Any] | None = None
    code_patch: dict[str, Any] | None = None
    worktree_path: str | None = None
    repair_attempts: int = 0
    test_results: list[dict[str, Any]] = field(default_factory=list)
    review_decision: str | None = None
    repo_gate_passed: bool = False
    git_branch: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None
    error_message: str | None = None

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def mark_updated(self) -> None:
        """Updates the updated_at timestamp to current UTC time."""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Converts JobState into a clean, JSON-serializable dictionary."""
        data = asdict(self)
        data["execution_policy"] = self.execution_policy.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobState":
        """Reconstructs a JobState instance from a dictionary representation."""
        data_copy = dict(data)
        if "execution_policy" in data_copy and isinstance(data_copy["execution_policy"], str):
            data_copy["execution_policy"] = ExecutionPolicy(data_copy["execution_policy"])
        if "status" in data_copy and isinstance(data_copy["status"], str):
            data_copy["status"] = JobStatus(data_copy["status"])
        return cls(**data_copy)

    def save(self, file_path: str | Path) -> None:
        """Saves JobState to a local JSON file for recovery and auditing."""
        self.mark_updated()
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), default=_json_serializer, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, file_path: str | Path) -> "JobState":
        """Loads a JobState instance from a local JSON file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"JobState file not found at {path}")
        raw_data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw_data)
