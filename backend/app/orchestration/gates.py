"""
Phase 10C: Gate 1 (Plan) and Gate 2 (Patch) Approval Engine
Enforces policy-driven human-in-the-loop and autonomous approval thresholds.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from app.agents.coder.models import CodePatch, ExecutionPolicy
from app.agents.coder.repo_gate import FinalGateResult
from app.agents.coder.reviewer import ReviewResult
from app.agents.plan_models import ImplementationPlan
from app.execution.models import TestResult

logger = logging.getLogger(__name__)


class GateStatus(str, Enum):
    """Gate approval status taxonomy."""

    APPROVED = "APPROVED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


@dataclass
class Gate1Report:
    """Detailed evaluation report for Gate 1 (Plan Approval)."""

    status: GateStatus
    summary: str
    files_to_modify: list[str] = field(default_factory=list)
    requires_user_approval: bool = False


@dataclass
class Gate2Report:
    """Detailed evaluation report for Gate 2 (Patch & Test Approval)."""

    status: GateStatus
    summary: str
    files_changed_count: int = 0
    lines_added_count: int = 0
    lines_deleted_count: int = 0
    tests_passed: bool = False
    repo_gate_passed: bool = False
    requires_user_approval: bool = False


class GateManager:
    """Manages Gate 1 (Plan) and Gate 2 (Patch) evaluation and approval decisions."""

    @classmethod
    def evaluate_gate_1(
        self,
        plan: ImplementationPlan,
        policy: ExecutionPolicy,
        user_approved: bool | None = None,
    ) -> Gate1Report:
        """Evaluates Gate 1 (ImplementationPlan approval) under the active execution policy."""
        files = sorted(list(plan.allowed_files))

        if policy == ExecutionPolicy.MANUAL:
            if user_approved is True:
                return Gate1Report(
                    status=GateStatus.APPROVED,
                    summary="Gate 1 Plan manually approved by user.",
                    files_to_modify=files,
                    requires_user_approval=True,
                )
            elif user_approved is False:
                return Gate1Report(
                    status=GateStatus.REJECTED,
                    summary="Gate 1 Plan rejected by user.",
                    files_to_modify=files,
                    requires_user_approval=True,
                )
            else:
                return Gate1Report(
                    status=GateStatus.AWAITING_APPROVAL,
                    summary="Gate 1 Plan awaiting user approval under MANUAL policy.",
                    files_to_modify=files,
                    requires_user_approval=True,
                )

        # SEMI_AUTONOMOUS / AUTONOMOUS: Auto-approve unless risk thresholds exceeded
        if len(files) > 3:
            if user_approved is True:
                return Gate1Report(
                    status=GateStatus.APPROVED,
                    summary="Gate 1 Plan (high file count) manually approved.",
                    files_to_modify=files,
                    requires_user_approval=True,
                )
            return Gate1Report(
                status=GateStatus.AWAITING_APPROVAL,
                summary=f"Gate 1 Plan touches {len(files)} files (>3 limit); requires approval.",
                files_to_modify=files,
                requires_user_approval=True,
            )

        return Gate1Report(
            status=GateStatus.APPROVED,
            summary="Gate 1 Plan auto-approved.",
            files_to_modify=files,
            requires_user_approval=False,
        )

    @classmethod
    def evaluate_gate_2(
        self,
        patch: CodePatch,
        test_result: TestResult | None,
        repo_gate_result: FinalGateResult | None,
        review_result: ReviewResult | None,
        policy: ExecutionPolicy,
        user_approved: bool | None = None,
    ) -> Gate2Report:
        """Evaluates Gate 2 (Patch diff stats & test pass verification)."""
        files_count = len(patch.files_changed)
        lines_added = 0
        for hunk in patch.hunks:
            if hunk.target_symbol and hunk.target_symbol.replacement_code:
                lines_added += len(hunk.target_symbol.replacement_code.splitlines())

        tests_passed = test_result.passed if test_result else False
        repo_gate_passed = repo_gate_result.passed if repo_gate_result else False

        # Non-bypassable failure checks
        if not tests_passed or not repo_gate_passed:
            return Gate2Report(
                status=GateStatus.REJECTED,
                summary="Gate 2 Patch rejected: Tests or Repository Integrity Gate failed.",
                files_changed_count=files_count,
                lines_added_count=lines_added,
                tests_passed=tests_passed,
                repo_gate_passed=repo_gate_passed,
                requires_user_approval=False,
            )

        if policy == ExecutionPolicy.AUTONOMOUS:
            return Gate2Report(
                status=GateStatus.APPROVED,
                summary="Gate 2 Patch auto-approved under AUTONOMOUS policy.",
                files_changed_count=files_count,
                lines_added_count=lines_added,
                tests_passed=tests_passed,
                repo_gate_passed=repo_gate_passed,
                requires_user_approval=False,
            )

        # MANUAL / SEMI_AUTONOMOUS require user approval
        if user_approved is True:
            return Gate2Report(
                status=GateStatus.APPROVED,
                summary="Gate 2 Patch manually approved by user.",
                files_changed_count=files_count,
                lines_added_count=lines_added,
                tests_passed=tests_passed,
                repo_gate_passed=repo_gate_passed,
                requires_user_approval=True,
            )
        elif user_approved is False:
            return Gate2Report(
                status=GateStatus.REJECTED,
                summary="Gate 2 Patch rejected by user.",
                files_changed_count=files_count,
                lines_added_count=lines_added,
                tests_passed=tests_passed,
                repo_gate_passed=repo_gate_passed,
                requires_user_approval=True,
            )

        return Gate2Report(
            status=GateStatus.AWAITING_APPROVAL,
            summary="Gate 2 Patch awaiting user approval.",
            files_changed_count=files_count,
            lines_added_count=lines_added,
            tests_passed=tests_passed,
            repo_gate_passed=repo_gate_passed,
            requires_user_approval=True,
        )
