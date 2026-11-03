"""
Evidence-Driven Planning Agent

Turns an IssueUnderstanding and EvidenceGraph into an ImplementationPlan. Strong evidence
is planned deterministically (no LLM); weak evidence goes to the LLM, whose reply is
schema-checked and validated against the repository listing. Paths are never invented
or corrected: anything that doesn't exist where it must is recorded as rejected.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import ClassVar

from app.agents.evidence.models import EvidenceGraph
from app.agents.llm_service import LLMService
from app.agents.models import IssueUnderstanding
from app.agents.plan_models import (
    FileAction,
    FileActionType,
    ImplementationPlan,
    PlanSource,
    PlanTask,
    RejectedAction,
)
from app.agents.plan_schema import (
    LLMPlanResponse,
    PlanParseError,
    PlanValidation,
    action_rejection,
    parse_plan_response,
    repo_dirs,
    validate_plan_semantics,
)
from app.repository.listing import is_test_path

logger = logging.getLogger(__name__)

MAX_PROMPT_FILES = 200
LLM_ATTEMPTS = 2  # the first try plus one re-prompt quoting the error


@dataclass
class _LLMAttempts:
    """What the LLM produced across attempts: an accepted plan, or the last failure."""

    response: LLMPlanResponse | None = None
    validation: PlanValidation | None = None
    error: str = ""
    rejected: list[RejectedAction] = field(default_factory=list)


class PlanningAgent:
    """Plans file actions from evidence, failing closed on every path."""

    SYSTEM_PLANNER_PROMPT: ClassVar[str] = (
        "You are Forge's Planning Agent. Given an issue and repository evidence, produce a "
        "minimal implementation plan as a single JSON object matching the given schema. "
        "Never invent file paths or symbols."
    )

    def __init__(self, llm_service: LLMService | None, valid_files: frozenset[str]) -> None:
        """llm_service may be None: weak evidence then falls back to a deterministic plan."""
        if not valid_files:
            raise ValueError("valid_files is empty; refusing to plan without a file listing")
        self._llm = llm_service
        self._valid_files = frozenset(valid_files)
        self._dirs = repo_dirs(self._valid_files)

    async def synthesize_plan(
        self,
        understanding: IssueUnderstanding,
        graph: EvidenceGraph,
        *,
        force_llm: bool = False,
    ) -> ImplementationPlan:
        """Routes to the LLM when forced or when the evidence gate found evidence weak."""
        if force_llm or not graph.is_sufficient:
            return await self._plan_via_llm(understanding, graph)
        return self._plan_deterministically(understanding, graph, PlanSource.DETERMINISTIC)

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    async def _plan_via_llm(
        self, understanding: IssueUnderstanding, graph: EvidenceGraph
    ) -> ImplementationPlan:
        tokens_before = self._tokens_spent()
        attempts = await self._run_llm_attempts(self._build_prompt(understanding, graph))
        tokens_used = self._tokens_spent() - tokens_before

        if attempts.response is None or attempts.validation is None:
            reason = f"LLM planning failed after {LLM_ATTEMPTS} attempts: {attempts.error}"
            logger.warning("Falling back to deterministic plan: %s", reason)
            plan = self._plan_deterministically(
                understanding, graph, PlanSource.DETERMINISTIC_FALLBACK
            )
            plan.warnings.append(reason)
            plan.rejected_actions = attempts.rejected + plan.rejected_actions
            plan.tokens_used = tokens_used
            return plan

        resp, validation = attempts.response, attempts.validation
        return ImplementationPlan.create(
            repository_id=graph.repository_id,
            summary=resp.summary,
            file_actions=validation.accepted,
            tasks=[
                PlanTask(t.step_number, t.title, t.description, t.target_file) for t in resp.tasks
            ],
            confidence_score=(
                resp.confidence if resp.confidence is not None else graph.top_confidence
            ),
            evidence_graph_id=graph.graph_id,
            tokens_used=tokens_used,
            source=PlanSource.LLM,
            intent=resp.intent.value,
            rationale=resp.rationale,
            test_targets=self._merge_test_targets(validation.test_targets, understanding),
            rejected_actions=validation.rejected,
            warnings=validation.warnings,
        )

    async def _run_llm_attempts(self, prompt: str) -> _LLMAttempts:
        """Asks once, re-asks once quoting the error, and stops at the first usable plan."""
        attempts = _LLMAttempts()
        if self._llm is None:
            attempts.error = "no LLM service is configured"
            return attempts
        for _ in range(LLM_ATTEMPTS):
            try:
                reply = await self._llm.generate_completion(
                    prompt=_with_retry_note(prompt, attempts.error),
                    system_prompt=self.SYSTEM_PLANNER_PROMPT,
                )
            except Exception as exc:  # network, timeout, auth: retrying won't help
                attempts.error = f"LLM call failed: {exc}"
                break
            try:
                resp = parse_plan_response(reply)
            except PlanParseError as exc:
                attempts.error = str(exc)
                continue
            validation = validate_plan_semantics(resp, self._valid_files)
            if validation.accepted:
                attempts.response, attempts.validation = resp, validation
                return attempts
            attempts.rejected = validation.rejected
            attempts.error = "every file action was rejected: " + "; ".join(
                f"{r.action_type} {r.file_path} ({r.reason})" for r in validation.rejected
            )
        return attempts

    def _build_prompt(self, understanding: IssueUnderstanding, graph: EvidenceGraph) -> str:
        allowed = self._prompt_files(understanding, graph)
        context = {
            "title": understanding.raw_title,
            "description": understanding.raw_description,
            "hypotheses": [
                {
                    "target_symbol": h.target_symbol,
                    "target_file": h.target_file,
                    "proposed_action": h.proposed_action,
                    "computed_confidence": h.computed_confidence,
                }
                for h in graph.hypotheses
            ],
            "relevant_tests": self._grounded_tests(understanding.relevant_tests),
            "constraints": understanding.constraints,
            "requested_actions": understanding.requested_actions,
            "unresolved_paths": understanding.unresolved_paths,
        }
        omitted = len(self._valid_files) - len(allowed)
        return "\n\n".join(
            [
                f"Issue and evidence:\n{json.dumps(context, indent=2)}",
                "Repository files (MODIFY/DELETE must use one of these; CREATE must be a new "
                "file in an existing directory):\n"
                + "\n".join(allowed)
                + (f"\n(... {omitted} more files not shown)" if omitted > 0 else ""),
                f"JSON schema:\n{json.dumps(LLMPlanResponse.model_json_schema())}",
                "Return ONLY JSON; paths outside the list are rejected.",
            ]
        )

    def _prompt_files(self, understanding: IssueUnderstanding, graph: EvidenceGraph) -> list[str]:
        """The file list shown to the LLM: evidence-backed files first, then the rest."""
        preferred = [f.file_path for f in understanding.affected_files]
        preferred += [h.target_file for h in graph.hypotheses if h.target_file]
        preferred += understanding.relevant_tests
        ordered = dict.fromkeys(p for p in preferred if p in self._valid_files)
        ordered.update(dict.fromkeys(sorted(self._valid_files)))
        return list(ordered)[:MAX_PROMPT_FILES]

    def _tokens_spent(self) -> int:
        if self._llm is None:
            return 0
        return self._llm.total_prompt_tokens + self._llm.total_completion_tokens

    # ------------------------------------------------------------------
    # Deterministic path
    # ------------------------------------------------------------------

    def _plan_deterministically(
        self, understanding: IssueUnderstanding, graph: EvidenceGraph, source: PlanSource
    ) -> ImplementationPlan:
        """One action per hypothesis that names a file; hypotheses without one are skipped."""
        actions: list[FileAction] = []
        rejected: list[RejectedAction] = []
        for hyp in graph.hypotheses:
            if not hyp.target_file:
                continue
            try:
                action_type = FileActionType.parse(hyp.proposed_action)
            except ValueError:
                rejected.append(
                    RejectedAction(hyp.target_file, hyp.proposed_action, "unknown action type")
                )
                continue
            reason = action_rejection(action_type, hyp.target_file, self._valid_files, self._dirs)
            if reason is None and any(a.file_path == hyp.target_file for a in actions):
                reason = "duplicate action for the same file"
            if reason is not None:
                rejected.append(RejectedAction(hyp.target_file, action_type.value, reason))
                continue
            actions.append(
                FileAction(
                    action_type=action_type,
                    file_path=hyp.target_file,
                    target_symbols=[hyp.target_symbol],
                    description=f"{action_type.value} {hyp.target_symbol} to resolve the issue",
                )
            )

        tasks = [
            PlanTask(
                step_number=i,
                title=f"{a.action_type.value.title()} {', '.join(a.target_symbols)}",
                description=a.description,
                target_file=a.file_path,
            )
            for i, a in enumerate(actions, start=1)
        ]
        return ImplementationPlan.create(
            repository_id=graph.repository_id,
            summary=(
                f"Evidence-driven plan for intent '{understanding.intent.value}' "
                f"targeting {len(actions)} file(s)."
            ),
            file_actions=actions,
            tasks=tasks,
            confidence_score=graph.top_confidence,
            evidence_graph_id=graph.graph_id,
            source=source,
            intent=understanding.intent.value,
            rationale=graph.routing_reason,
            test_targets=self._merge_test_targets([], understanding),
            rejected_actions=rejected,
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def _grounded_tests(self, paths: list[str]) -> list[str]:
        return [p for p in paths if p in self._valid_files and is_test_path(p)]

    def _merge_test_targets(
        self, validated: list[str], understanding: IssueUnderstanding
    ) -> list[str]:
        """Validated LLM targets plus grounded issue tests, deduplicated in order."""
        return list(dict.fromkeys(validated + self._grounded_tests(understanding.relevant_tests)))


def _with_retry_note(prompt: str, error: str) -> str:
    if not error:
        return prompt
    return (
        f"{prompt}\n\nYour previous reply was rejected: {error}\n"
        "Fix it and return ONLY the corrected JSON object."
    )
