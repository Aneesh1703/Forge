"""
Phase 9A: Complexity Scorer Engine
Calculates AST & graph metric complexity to assign model tiers & token budgets.
"""

from app.agents.coder.models import ComplexityScore, ModelTier
from app.agents.plan_models import ImplementationPlan


class ComplexityScorer:
    """Evaluates graph fan-out & change scope to assign adaptive token budgets."""

    @classmethod
    def evaluate(
        self,
        plan: ImplementationPlan,
        attempt_number: int = 1,
        has_api_changes: bool = False,
        has_schema_changes: bool = False,
    ) -> ComplexityScore:
        """Calculates complexity score (0-100) and returns assigned token budget & model tier."""
        base_score = 10

        # Scope metrics
        file_count = len(plan.allowed_files)
        task_count = len(plan.tasks)
        base_score += file_count * 15
        base_score += task_count * 5

        if has_api_changes:
            base_score += 20
        if has_schema_changes:
            base_score += 25

        # Progressive attempt escalation
        if attempt_number > 1:
            base_score += (attempt_number - 1) * 20

        # Cap score between 0 and 100
        score = max(0, min(100, base_score))

        # Assign tier & token budget
        if score <= 30:
            tier = ModelTier.LEVEL_1_FAST
            budget = 4000
        elif score <= 60:
            tier = ModelTier.LEVEL_2_STRONG
            budget = 8000
        elif score <= 80:
            tier = ModelTier.LEVEL_2_STRONG
            budget = 12000
        else:
            tier = ModelTier.LEVEL_3_FLAGSHIP
            budget = 15000

        # Progressive budget increase for retries
        if attempt_number > 1:
            budget = int(budget * (1.0 + 0.5 * (attempt_number - 1)))

        summary = (
            f"Complexity score: {score}/100 | Tier: {tier.value} | "
            f"Files: {file_count} | Tasks: {task_count} | Attempt: {attempt_number}"
        )

        return ComplexityScore(
            score=score,
            tier=tier,
            token_budget=budget,
            reasoning_summary=summary,
        )
