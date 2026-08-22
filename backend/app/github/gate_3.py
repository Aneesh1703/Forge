"""
Phase 10E: Gate 3 PR Publication Approval & GitHub CI Check Monitoring Service.
"""

import json
import logging
import urllib.request
from dataclasses import dataclass
from enum import Enum

from app.agents.coder.models import CodePatch, ExecutionPolicy
from app.agents.coder.repo_gate import FinalGateResult
from app.agents.plan_models import ImplementationPlan
from app.execution.models import TestResult
from app.github.auth import CompositeGitHubAuth, GitHubAuthProvider
from app.orchestration.gates import GateStatus

logger = logging.getLogger(__name__)


class CICheckStatus(str, Enum):
    """Remote GitHub CI Check status taxonomy."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    NEUTRAL = "NEUTRAL"


@dataclass
class Gate3Report:
    """Detailed evaluation report for Gate 3 (PR Publication Approval)."""

    status: GateStatus
    summary: str
    target_branch: str = "main"
    feature_branch: str = ""
    requires_user_approval: bool = False


class Gate3Approval:
    """Enforces Gate 3 PR publication approval policy bounds."""

    @classmethod
    def evaluate_gate_3(
        cls,
        plan: ImplementationPlan,
        patch: CodePatch,
        test_result: TestResult | None,
        repo_gate_result: FinalGateResult | None,
        policy: ExecutionPolicy,
        feature_branch: str,
        target_branch: str = "main",
        user_approved: bool | None = None,
    ) -> Gate3Report:
        """Evaluates Gate 3 approval before remote push and PR creation."""
        tests_passed = test_result.passed if test_result else False
        repo_gate_passed = repo_gate_result.passed if repo_gate_result else False

        if not tests_passed or not repo_gate_passed:
            return Gate3Report(
                status=GateStatus.REJECTED,
                summary="Gate 3 PR creation blocked: Tests or Repo Integrity Gate failed.",
                target_branch=target_branch,
                feature_branch=feature_branch,
                requires_user_approval=False,
            )

        if policy == ExecutionPolicy.AUTONOMOUS:
            return Gate3Report(
                status=GateStatus.APPROVED,
                summary="Gate 3 PR publication auto-approved under AUTONOMOUS policy.",
                target_branch=target_branch,
                feature_branch=feature_branch,
                requires_user_approval=False,
            )

        # MANUAL / SEMI_AUTONOMOUS
        if user_approved is True:
            return Gate3Report(
                status=GateStatus.APPROVED,
                summary="Gate 3 PR publication manually approved by user.",
                target_branch=target_branch,
                feature_branch=feature_branch,
                requires_user_approval=True,
            )
        elif user_approved is False:
            return Gate3Report(
                status=GateStatus.REJECTED,
                summary="Gate 3 PR publication rejected by user.",
                target_branch=target_branch,
                feature_branch=feature_branch,
                requires_user_approval=True,
            )

        return Gate3Report(
            status=GateStatus.AWAITING_APPROVAL,
            summary="Gate 3 PR publication awaiting user approval.",
            target_branch=target_branch,
            feature_branch=feature_branch,
            requires_user_approval=True,
        )


class GitHubCICheckMonitor:
    """Monitors remote GitHub Actions check runs for a commit ref or pull request."""

    def __init__(
        self,
        auth_provider: GitHubAuthProvider | None = None,
        api_base_url: str = "https://api.github.com",
    ) -> None:
        self.auth_provider = auth_provider or CompositeGitHubAuth()
        self.api_base_url = api_base_url.rstrip("/")

    def get_commit_check_status(self, owner: str, repo: str, ref: str) -> CICheckStatus:
        """Queries GitHub REST API for check-runs status on a ref."""
        token = self.auth_provider.get_token()
        if not token:
            logger.warning("No GitHub auth token available for CI status check.")
            return CICheckStatus.NEUTRAL

        url = f"{self.api_base_url}/repos/{owner}/{repo}/commits/{ref}/check-runs"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Forge-Engine-Agent",
        }

        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                check_runs = data.get("check_runs", [])

                if not check_runs:
                    return CICheckStatus.NEUTRAL

                for run in check_runs:
                    status = run.get("status")
                    conclusion = run.get("conclusion")

                    if status != "completed":
                        return CICheckStatus.PENDING
                    if conclusion and conclusion not in ("success", "neutral", "skipped"):
                        return CICheckStatus.FAILURE

                return CICheckStatus.SUCCESS
        except Exception as e:
            logger.warning(f"Error querying GitHub CI checks for {ref}: {e}")
            return CICheckStatus.NEUTRAL
