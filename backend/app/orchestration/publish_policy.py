"""
Publish policy: decides whether a finished job may commit and publish without a human.

Kept as a pure function so every policy outcome is unit-testable without git or an LLM.
"""

from dataclasses import dataclass, field

from app.agents.coder.reviewer import ReviewDecision, ReviewResult


@dataclass(frozen=True)
class PublishDecision:
    """Whether the pipeline may publish automatically, and why not if it may not."""

    auto_publish: bool
    reasons: list[str] = field(default_factory=list)


def decide_publish(
    tests_passed: bool,
    repo_gate_passed: bool,
    review: ReviewResult,
) -> PublishDecision:
    """Auto-publish only when tests pass, the repo gate passes, and the reviewer approves
    without requiring a human. Applies to every policy, including AUTONOMOUS."""
    reasons: list[str] = []
    if not tests_passed:
        reasons.append("Tests did not pass.")
    if not repo_gate_passed:
        reasons.append("Repository safety gate failed.")
    if review.decision != ReviewDecision.APPROVED:
        reasons.append(f"Reviewer decision: {review.decision.value}.")
    elif review.requires_user_approval:
        reasons.append("Execution policy requires human approval at Gate 2.")
    return PublishDecision(auto_publish=not reasons, reasons=reasons)
