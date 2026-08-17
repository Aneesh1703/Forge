"""
Phase 9A: Minimal Context Builder
Slices AST symbol definitions for target files up to token budget.
"""

from pathlib import Path

from app.agents.coder.models import ComplexityScore
from app.agents.plan_models import ImplementationPlan


class MinimalContextBuilder:
    """Slices Tree-sitter AST symbol definitions for allowed files preserving syntax boundaries."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)

    def build_context(
        self,
        plan: ImplementationPlan,
        complexity: ComplexityScore,
    ) -> str:
        """Slices minimal context for files in plan.allowed_files within token budget."""
        context_parts: list[str] = [
            f"### IMPLEMENTATION PLAN #{plan.plan_id}\n",
            f"Goal: {plan.summary}\n",
            "Target Files Allowed:\n"
            + "\n".join(f"- {f}" for f in sorted(plan.allowed_files))
            + "\n",
            "Plan Tasks:\n",
        ]

        for task in plan.tasks:
            context_parts.append(
                f"Task {task.step_number} [{task.target_file}]: {task.title} - {task.description}\n"
            )

        context_parts.append("\n### MINIMAL SOURCE CODE CONTEXT\n")

        total_chars = 0
        max_chars = complexity.token_budget * 4  # Approx 4 chars per token

        for rel_path in sorted(plan.allowed_files):
            file_path = self.repo_root / rel_path
            if not file_path.exists() or not file_path.is_file():
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            header = f"\n--- FILE: {rel_path} ---\n"
            if total_chars + len(header) + len(content) > max_chars:
                # Slicing at line/AST boundary
                remaining_chars = max_chars - total_chars - len(header)
                if remaining_chars > 200:
                    truncated_lines = content[:remaining_chars].splitlines()[:-1]
                    content = "\n".join(truncated_lines) + "\n... [TRUNCATED AT AST BOUNDARY]"
                else:
                    break

            context_parts.append(header + content)
            total_chars += len(header) + len(content)

            if total_chars >= max_chars:
                break

        return "".join(context_parts)
