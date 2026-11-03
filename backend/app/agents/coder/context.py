"""
Phase 9A: Multi-File Context Builder
Slices AST symbol definitions and multi-file candidate context up to 8k-16k token budgets.
"""

import ast
from pathlib import Path
from typing import Any

from app.agents.candidate.models import CandidateContext, CandidateFile, CandidateScore
from app.agents.coder.models import ComplexityScore
from app.agents.plan_models import FileActionType, ImplementationPlan


def plan_context(
    plan: ImplementationPlan, repo_root: str | Path, issue_prompt: str
) -> CandidateContext:
    """The coder's context is exactly the plan's existing files and test targets.

    Files the plan creates don't exist yet, so they have nothing to show; the plan itself
    tells the coder about them.
    """
    root = Path(repo_root).resolve()

    def existing(paths: list[str], is_test: bool) -> list[CandidateFile]:
        return [
            CandidateFile(
                file_path=p, abs_path=root / p, score=CandidateScore(p), is_test_file=is_test
            )
            for p in dict.fromkeys(paths)
            if (root / p).is_file()
        ]

    source_files = [
        fa.file_path for fa in plan.file_actions if fa.action_type != FileActionType.CREATE
    ]
    return CandidateContext(
        issue_prompt=issue_prompt,
        candidate_files=existing(source_files, is_test=False),
        test_files=existing(plan.test_targets, is_test=True),
    )


class MultiFileContextBuilder:
    """Assembles rich multi-file candidate context with Call-Graph and AST diagnostics."""

    def __init__(
        self,
        repo_root: str | Path,
        soft_token_budget: int = 8000,
        hard_token_budget: int = 16000,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.soft_token_budget = soft_token_budget
        self.hard_token_budget = hard_token_budget

    def build_multifile_context(
        self,
        candidate_ctx: CandidateContext,
        graph_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Builds structured minimal context across top candidate files and test cases."""
        context_parts: list[str] = [
            f"### MULTI-FILE CANDIDATE CONTEXT FOR ISSUE: {candidate_ctx.issue_prompt}\n",
            f"Candidate Files Discovered: {len(candidate_ctx.candidate_files)}\n",
        ]

        if graph_metadata:
            context_parts.append("\n--- CALL-GRAPH & AST DIAGNOSTICS ---\n")
            for key, val in graph_metadata.items():
                context_parts.append(f"• {key}: {val}\n")

        total_chars = 0
        max_chars = self.hard_token_budget * 4  # Approx 4 chars per token

        context_parts.append("\n--- CANDIDATE FILE SNIPPETS ---\n")

        # Include main candidate files
        for cf in candidate_ctx.candidate_files:
            file_p = self.repo_root / cf.file_path
            if not file_p.exists() or not file_p.is_file():
                continue

            try:
                raw_code = file_p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            header = f"\n=== CANDIDATE FILE: {cf.file_path} (Score: {cf.score.total_score}) ===\n"

            # Check AST validity for diagnostics
            syntax_diag = ""
            try:
                ast.parse(raw_code)
            except (SyntaxError, IndentationError) as err:
                syntax_diag = f"⚠️ AST Diagnostic Warning: {err}\n"

            block = header + syntax_diag + raw_code + "\n"

            if total_chars + len(block) > max_chars:
                rem_chars = max_chars - total_chars - len(header)
                if rem_chars > 200:
                    truncated = raw_code[:rem_chars].rsplit("\n", 1)[0]
                    context_parts.append(
                        header + syntax_diag + truncated + "\n... [TRUNCATED AT AST BOUNDARY]\n"
                    )
                break
            else:
                context_parts.append(block)
                total_chars += len(block)

        # Include test files if budget remains
        if candidate_ctx.test_files and total_chars < self.soft_token_budget * 4:
            context_parts.append("\n--- RELEVANT TEST CASES ---\n")
            for tf in candidate_ctx.test_files:
                test_p = self.repo_root / tf.file_path
                if not test_p.exists():
                    continue
                try:
                    raw_test = test_p.read_text(encoding="utf-8", errors="replace")
                    t_header = f"\n=== TEST FILE: {tf.file_path} ===\n"
                    block = t_header + raw_test[:2000] + "\n"
                    if total_chars + len(block) <= max_chars:
                        context_parts.append(block)
                        total_chars += len(block)
                except Exception:
                    pass

        return "".join(context_parts)


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
        max_chars = complexity.token_budget * 4

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

    def get_symbol_snippet_with_context(self, rel_path: str, issue_prompt: str = "") -> str:
        """Extracts AST target symbol definition with line numbers and context lines."""
        file_path = self.repo_root / rel_path
        if not file_path.exists():
            return ""

        try:
            raw_code = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(raw_code)
            lines = raw_code.splitlines()
        except Exception:
            return ""

        issue_lower = issue_prompt.lower()
        matching_node: ast.AST | None = None

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.lower() in issue_lower or any(
                    kw in issue_lower for kw in node.name.split("_")
                ):
                    matching_node = node
                    break

        if not matching_node:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    matching_node = node
                    break

        if (
            matching_node
            and hasattr(matching_node, "lineno")
            and hasattr(matching_node, "end_lineno")
        ):
            start_line = max(1, matching_node.lineno - 5)
            end_line = min(len(lines), (matching_node.end_lineno or matching_node.lineno) + 5)

            snippet_lines = [f"{i:4d} | {lines[i - 1]}" for i in range(start_line, end_line + 1)]
            node_name = getattr(matching_node, "name", "symbol")
            return (
                f"--- TARGET AST SYMBOL: `{node_name}` (Lines {start_line}-{end_line}) ---\n"
                + "\n".join(snippet_lines)
                + "\n"
            )

        return ""
