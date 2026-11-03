"""
LLM Plan Response Schema & Validation

The planner LLM's reply is untrusted text. It is parsed into strict pydantic models
(unknown keys rejected), then checked against the real repository listing. Paths are
never guessed or corrected: anything that does not fit is recorded as rejected.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.agents.models import IssueIntent
from app.agents.plan_models import FileAction, FileActionType, RejectedAction
from app.repository.listing import is_test_path

_DRIVE = re.compile(r"^[A-Za-z]:")
_MAX_ERRORS_QUOTED = 3


class PlanParseError(ValueError):
    """The LLM reply could not be read as a plan; the message is short enough to quote back."""


def path_problem(path: str) -> str | None:
    """Why a path is not a canonical repo-relative file path, or None if it is.

    Non-canonical spellings ("a//b", "a/./b", "a/") are refused rather than rewritten,
    so existence and duplicate checks always compare one spelling per file.
    """
    if not path or path == ".":
        return "path is empty"
    if not path.isprintable():
        return "path must not contain control characters"
    if "\\" in path:
        return "path must use forward slashes"
    if path.startswith("/") or _DRIVE.match(path):
        return "path must be relative to the repository root"
    if ".." in PurePosixPath(path).parts:
        return "path must not contain '..'"
    if str(PurePosixPath(path)) != path:
        return "path must be in canonical form (no '//', '/./' or trailing '/')"
    return None


def _clean_relative_path(raw: str) -> str:
    """Drops a leading "./" and refuses anything else that isn't a canonical relative path."""
    path = raw.strip()
    while path.startswith("./"):
        path = path[2:]
    problem = path_problem(path)
    if problem is not None:
        raise ValueError(problem)
    return path


class LLMFileAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: FileActionType
    file_path: str
    description: str
    target_symbols: list[str] = []

    @field_validator("file_path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return _clean_relative_path(value)


class LLMTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(ge=1)
    title: str
    description: str
    target_file: str = ""


class LLMPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    intent: IssueIntent
    file_actions: list[LLMFileAction] = Field(min_length=1, max_length=20)
    tasks: list[LLMTask] = Field(min_length=1)
    rationale: str = ""
    test_targets: list[str] = []
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def _balanced_object_at(text: str, start: int) -> str | None:
    """The balanced {...} starting at text[start]; braces inside JSON strings don't count."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _json_object_candidates(text: str) -> Iterator[str]:
    """Every balanced {...} in the reply, in order of where it starts.

    Scanning the raw text (instead of cutting out a markdown fence first) means other
    code blocks, or backticks inside JSON strings, can't hide the plan.
    """
    for start, ch in enumerate(text):
        if ch == "{" and (obj := _balanced_object_at(text, start)) is not None:
            yield obj


def _is_json_object(candidate: str) -> bool:
    try:
        return isinstance(json.loads(candidate), dict)
    except ValueError:
        return False


def _summarise_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:_MAX_ERRORS_QUOTED]:
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    more = exc.error_count() - _MAX_ERRORS_QUOTED
    if more > 0:
        parts.append(f"and {more} more error(s)")
    return "invalid plan JSON: " + "; ".join(parts)


def parse_plan_response(raw: str) -> LLMPlanResponse:
    """Reads a plan from an LLM reply that may wrap the JSON in fences or prose.

    The first {...} that validates wins. If none does, the error quoted back is the one
    for the first candidate that is at least real JSON, so the model sees what it got
    wrong about the plan rather than about some stray brace in its prose.
    """
    errors: list[tuple[str, ValidationError]] = []
    for candidate in _json_object_candidates(raw):
        try:
            return LLMPlanResponse.model_validate_json(candidate)
        except ValidationError as exc:
            errors.append((candidate, exc))
    if "{" not in raw:
        raise PlanParseError("reply contains no JSON object")
    if not errors:
        raise PlanParseError("reply has an unterminated JSON object")
    quoted = next((exc for c, exc in errors if _is_json_object(c)), errors[0][1])
    raise PlanParseError(_summarise_errors(quoted))


@dataclass(frozen=True)
class PlanValidation:
    """The LLM plan split into what the repository allows and what it refuses."""

    accepted: list[FileAction]
    rejected: list[RejectedAction]
    test_targets: list[str]
    warnings: list[str]


def repo_dirs(repo_files: frozenset[str]) -> frozenset[str]:
    """Every directory that holds at least one repository file ("" is the root)."""
    dirs = {""}
    for path in repo_files:
        dirs.update(str(parent) for parent in PurePosixPath(path).parents if str(parent) != ".")
    return frozenset(dirs)


def action_rejection(
    action_type: FileActionType,
    path: str,
    repo_files: frozenset[str],
    dirs: frozenset[str],
) -> str | None:
    """Why this action can't apply to the repository as it is, or None if it can."""
    problem = path_problem(path)
    if problem is not None:
        return problem
    if action_type is FileActionType.CREATE:
        if path in repo_files:
            return "CREATE target already exists"
        if path in dirs:
            return "CREATE target is an existing directory"
        parent = str(PurePosixPath(path).parent)
        if parent != "." and parent not in dirs:
            return f"CREATE parent directory '{parent}' does not exist"
        return None
    if path not in repo_files:
        return f"{action_type.value} target does not exist in the repository"
    return None


def validate_plan_semantics(resp: LLMPlanResponse, repo_files: frozenset[str]) -> PlanValidation:
    """Checks every proposed path against the repository listing, without correcting any."""
    dirs = repo_dirs(repo_files)
    accepted: list[FileAction] = []
    rejected: list[RejectedAction] = []
    seen: set[str] = set()
    for act in resp.file_actions:
        reason = action_rejection(act.action_type, act.file_path, repo_files, dirs)
        if reason is None and act.file_path in seen:
            reason = "duplicate action for the same file"
        if reason is not None:
            rejected.append(RejectedAction(act.file_path, act.action_type.value, reason))
            continue
        seen.add(act.file_path)
        accepted.append(
            FileAction(
                action_type=act.action_type,
                file_path=act.file_path,
                target_symbols=list(act.target_symbols),
                description=act.description,
            )
        )

    warnings: list[str] = []
    steps = [t.step_number for t in resp.tasks]
    duplicates = sorted({s for s in steps if steps.count(s) > 1})
    if duplicates:
        warnings.append(f"duplicate task step numbers: {duplicates}")

    test_targets: list[str] = []
    for target in resp.test_targets:
        if target in repo_files and is_test_path(target):
            if target not in test_targets:
                test_targets.append(target)
        else:
            warnings.append(f"dropped test target '{target}': not an existing test file")

    return PlanValidation(accepted, rejected, test_targets, warnings)
