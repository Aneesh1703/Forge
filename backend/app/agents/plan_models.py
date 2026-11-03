"""
Implementation Plan Domain Models

Defines FileActionType, FileAction, PlanTask, RejectedAction, and ImplementationPlan —
the plan contract persisted in JobState, rendered for humans, and consumed downstream.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PLAN_SCHEMA_VERSION = 1


class FileActionType(str, Enum):
    """Target action type for a file in an implementation plan."""

    MODIFY = "MODIFY"
    CREATE = "CREATE"
    DELETE = "DELETE"

    @classmethod
    def parse(cls, raw: Any) -> "FileActionType":
        """Accepts "MODIFY", "modify", or legacy "FileActionType.MODIFY" spellings."""
        return cls(str(raw).rsplit(".", 1)[-1].upper())


class PlanSource(str, Enum):
    """Which planner produced the plan."""

    INLINE = "inline"  # pipeline placeholder: every candidate file marked MODIFY
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


def _str_list(raw: Any) -> list[str]:
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _uuid_or_none(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "file_path": self.file_path,
            "target_symbols": list(self.target_symbols),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileAction":
        return cls(
            action_type=FileActionType.parse(data.get("action_type", "MODIFY")),
            file_path=str(data.get("file_path") or data.get("target_file") or ""),
            target_symbols=_str_list(data.get("target_symbols")),
            start_line=data.get("start_line"),
            end_line=data.get("end_line"),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class PlanTask:
    """
    Sequential step task in an implementation plan.
    """

    step_number: int
    title: str
    description: str
    target_file: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "title": self.title,
            "description": self.description,
            "target_file": self.target_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanTask":
        return cls(
            step_number=int(data.get("step_number", 0)),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            target_file=str(data.get("target_file", "")),
        )


@dataclass(frozen=True)
class RejectedAction:
    """A file action the planner proposed but validation refused, kept for the record."""

    file_path: str
    action_type: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"file_path": self.file_path, "action_type": self.action_type, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RejectedAction":
        return cls(
            file_path=str(data.get("file_path", "")),
            action_type=str(data.get("action_type", "")),
            reason=str(data.get("reason", "")),
        )


@dataclass
class ImplementationPlan:
    """
    Structured outcome of evidence-driven planning.

    test_targets are the only tests the pipeline executes; verification_commands are
    shown to humans and never run.
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
    source: PlanSource = PlanSource.INLINE
    intent: str = ""
    rationale: str = ""
    test_targets: list[str] = field(default_factory=list)
    rejected_actions: list[RejectedAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: int = PLAN_SCHEMA_VERSION

    # ------------------------------------------------------------------
    # File scopes
    # ------------------------------------------------------------------

    def _files_with(self, action_type: FileActionType) -> set[str]:
        return {fa.file_path for fa in self.file_actions if fa.action_type == action_type}

    @property
    def allowed_files(self) -> set[str]:
        """Set of target file paths authorized for change in this plan."""
        return {fa.file_path for fa in self.file_actions}

    @property
    def existing_files(self) -> set[str]:
        """Files the plan modifies in place."""
        return self._files_with(FileActionType.MODIFY)

    @property
    def created_files(self) -> set[str]:
        return self._files_with(FileActionType.CREATE)

    @property
    def deleted_files(self) -> set[str]:
        return self._files_with(FileActionType.DELETE)

    # ------------------------------------------------------------------
    # Construction & persistence
    # ------------------------------------------------------------------

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
        source: PlanSource = PlanSource.INLINE,
        intent: str = "",
        rationale: str = "",
        test_targets: list[str] | None = None,
        rejected_actions: list[RejectedAction] | None = None,
        warnings: list[str] | None = None,
    ) -> "ImplementationPlan":
        return cls(
            plan_id=uuid.uuid4(),
            repository_id=repository_id,
            summary=summary.strip(),
            file_actions=file_actions or [],
            tasks=tasks or [],
            verification_commands=verification_commands or [],
            evidence_graph_id=evidence_graph_id,
            confidence_score=confidence_score,
            tokens_used=tokens_used,
            source=source,
            intent=intent,
            rationale=rationale,
            test_targets=test_targets or [],
            rejected_actions=rejected_actions or [],
            warnings=warnings or [],
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation, the persisted plan contract."""
        return {
            "schema_version": self.schema_version,
            "plan_id": str(self.plan_id),
            "repository_id": str(self.repository_id),
            "summary": self.summary,
            "source": self.source.value,
            "intent": self.intent,
            "rationale": self.rationale,
            "file_actions": [fa.to_dict() for fa in self.file_actions],
            "tasks": [t.to_dict() for t in self.tasks],
            "test_targets": list(self.test_targets),
            "verification_commands": list(self.verification_commands),
            "rejected_actions": [r.to_dict() for r in self.rejected_actions],
            "warnings": list(self.warnings),
            "evidence_graph_id": str(self.evidence_graph_id) if self.evidence_graph_id else None,
            "confidence_score": self.confidence_score,
            "tokens_used": self.tokens_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImplementationPlan":
        """Reads to_dict output and legacy dataclasses.asdict job files (schema 0).

        Unknown keys are ignored and missing ones take defaults, so older and newer
        job files both load.
        """
        try:
            source = PlanSource(data.get("source", PlanSource.INLINE.value))
        except ValueError:
            source = PlanSource.INLINE
        return cls(
            plan_id=_uuid_or_none(data.get("plan_id")) or uuid.uuid4(),
            repository_id=_uuid_or_none(data.get("repository_id")) or uuid.uuid4(),
            summary=str(data.get("summary", "")),
            file_actions=[FileAction.from_dict(a) for a in data.get("file_actions") or []],
            tasks=[PlanTask.from_dict(t) for t in data.get("tasks") or []],
            verification_commands=_str_list(data.get("verification_commands")),
            evidence_graph_id=_uuid_or_none(data.get("evidence_graph_id")),
            confidence_score=float(data.get("confidence_score") or 0.0),
            tokens_used=int(data.get("tokens_used") or 0),
            source=source,
            intent=str(data.get("intent", "")),
            rationale=str(data.get("rationale", "")),
            test_targets=_str_list(data.get("test_targets")),
            rejected_actions=[
                RejectedAction.from_dict(r) for r in data.get("rejected_actions") or []
            ],
            warnings=_str_list(data.get("warnings")),
            schema_version=int(data.get("schema_version") or 0),
        )

    # ------------------------------------------------------------------
    # Human-readable rendering
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Renders the plan for Gate 1 review and PR descriptions."""
        lines = [f"# Plan: {self.summary or 'Untitled'}", ""]
        meta = [f"**Source:** {self.source.value}"]
        if self.intent:
            meta.append(f"**Intent:** {self.intent}")
        meta.append(f"**Confidence:** {self.confidence_score:.2f}")
        lines += [" · ".join(meta), ""]

        if self.rationale:
            lines += ["## Rationale", "", self.rationale, ""]

        lines += ["## Files", ""]
        if self.file_actions:
            lines += ["| Action | File | Symbols | Why |", "|---|---|---|---|"]
            for fa in self.file_actions:
                symbols = ", ".join(f"`{s}`" for s in fa.target_symbols) or "—"
                why = _md_cell(fa.description) or "—"
                lines.append(f"| {fa.action_type.value} | `{fa.file_path}` | {symbols} | {why} |")
        else:
            lines.append("_No file actions._")
        lines.append("")

        lines += ["## Steps", ""]
        if self.tasks:
            for task in sorted(self.tasks, key=lambda t: t.step_number):
                target = f" (`{task.target_file}`)" if task.target_file else ""
                lines.append(f"{task.step_number}. **{task.title}**{target} — {task.description}")
        else:
            lines.append("_No steps._")
        lines.append("")

        lines += ["## Tests to run", ""]
        lines += [f"- `{t}`" for t in self.test_targets] or ["_None selected._"]
        lines.append("")

        if self.verification_commands:
            lines += ["## Suggested verification (not executed)", ""]
            lines += [f"- `{c}`" for c in self.verification_commands]
            lines.append("")

        if self.rejected_actions:
            lines += ["## Rejected actions", ""]
            lines += [
                f"- {r.action_type} `{r.file_path}` — {r.reason}" for r in self.rejected_actions
            ]
            lines.append("")

        if self.warnings:
            lines += ["## Warnings", ""]
            lines += [f"- {w}" for w in self.warnings]
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def _md_cell(text: str) -> str:
    """Keeps free text from breaking a markdown table row."""
    return text.replace("|", "\\|").replace("\n", " ").strip()
