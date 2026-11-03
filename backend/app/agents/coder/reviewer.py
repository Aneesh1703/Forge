"""
Phase 9F: Final Reviewer Agent & Gate 2 Approval System
"""

from dataclasses import dataclass, field
from enum import Enum

from app.agents.coder.models import CodePatch, ExecutionPolicy, SymbolAction
from app.agents.plan_models import ImplementationPlan
from app.execution.models import TestResult

SEMI_AUTONOMOUS_MAX_LINES = 50
DESTRUCTIVE_ACTIONS = frozenset({SymbolAction.DELETE, SymbolAction.REPLACE_FILE})


class ReviewDecision(str, Enum):
    """Final patch review decision."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVISION = "NEEDS_REVISION"


@dataclass
class ReviewResult:
    """Structured report produced by FinalReviewerAgent."""

    decision: ReviewDecision
    confidence: float
    diff_summary: str
    lines_added: int
    lines_deleted: int
    comments: list[str] = field(default_factory=list)
    requires_user_approval: bool = True


class FinalReviewerAgent:
    """Evaluates proposed patches and enforces Gate 2 Patch Approval policy bounds."""

    def review_patch(
        self,
        plan: ImplementationPlan,
        patch: CodePatch,
        test_result: TestResult | None,
        policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS,
    ) -> ReviewResult:
        """Evaluates final patch quality and determines whether Gate 2 requires user approval."""
        comments: list[str] = []
        lines_added = 0
        lines_deleted = 0

        for hunk in patch.hunks:
            target = hunk.target_symbol
            added = len(target.replacement_code.splitlines())
            lines_added += added

        diff_summary = (
            f"Files changed: {len(patch.files_changed)} | "
            f"+{lines_added} lines | -{lines_deleted} lines"
        )

        # Basic health checks
        if test_result is None or not test_result.passed:
            comments.append(
                "Tests did not run on the final patch."
                if test_result is None
                else "Tests failed on final patch execution."
            )
            return ReviewResult(
                decision=ReviewDecision.REJECTED,
                confidence=0.0,
                diff_summary=diff_summary,
                lines_added=lines_added,
                lines_deleted=lines_deleted,
                comments=comments,
                requires_user_approval=True,
            )

        if not patch.files_changed:
            comments.append("No files were modified in patch.")
            return ReviewResult(
                decision=ReviewDecision.REJECTED,
                confidence=0.0,
                diff_summary=diff_summary,
                lines_added=0,
                lines_deleted=0,
                comments=comments,
                requires_user_approval=False,
            )

        # Policy-driven Gating Logic for Gate 2
        requires_user_approval = True
        confidence = patch.confidence

        if policy == ExecutionPolicy.AUTONOMOUS:
            requires_user_approval = False
            comments.append("Autonomous execution policy: Auto-approved Gate 2.")
        elif policy == ExecutionPolicy.SEMI_AUTONOMOUS:
            # Whole-file replacements and deletions can remove arbitrary amounts of code,
            # which lines_added cannot measure, so they always need a human.
            destructive = any(h.action in DESTRUCTIVE_ACTIONS for h in patch.hunks)
            if lines_added <= SEMI_AUTONOMOUS_MAX_LINES and not destructive:
                requires_user_approval = False
                comments.append("Semi-Autonomous policy: Low-risk patch auto-approved.")
            else:
                requires_user_approval = True
                comments.append("Semi-Autonomous policy: High-risk patch requires Gate 2 approval.")
        else:  # MANUAL
            requires_user_approval = True
            comments.append("Manual execution policy: Requires Gate 2 patch approval.")

        return ReviewResult(
            decision=ReviewDecision.APPROVED,
            confidence=confidence,
            diff_summary=diff_summary,
            lines_added=lines_added,
            lines_deleted=lines_deleted,
            comments=comments,
            requires_user_approval=requires_user_approval,
        )
