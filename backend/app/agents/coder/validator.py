"""
Phase 9B: Deterministic Patch Safety Gate Engine
Validates allowed_files scope, patch budget limits, source content hashes, and AST syntax.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.coder.models import CodePatch, SymbolTarget
from app.agents.plan_models import ImplementationPlan


@dataclass
class PatchValidationResult:
    """Detailed deterministic safety validation report."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    allowed_files_valid: bool = True
    budget_valid: bool = True
    hashes_valid: bool = True
    syntax_valid: bool = True


class PatchSafetyGate:
    """Enforces non-bypassable deterministic validation rules on generated patches."""

    def __init__(
        self,
        repo_root: str | Path,
        max_files: int = 5,
        max_hunks: int = 15,
        max_added_lines: int = 250,
        max_deleted_lines: int = 150,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.max_files = max_files
        self.max_hunks = max_hunks
        self.max_added_lines = max_added_lines
        self.max_deleted_lines = max_deleted_lines

    def validate(self, plan: ImplementationPlan, patch: CodePatch) -> PatchValidationResult:
        """Executes all deterministic safety checks against the patch and working tree."""
        result = PatchValidationResult()

        # 1. Allowed Files Boundary Check
        patch_files = set(patch.files_changed)
        unauthorized_files = patch_files - plan.allowed_files
        if unauthorized_files:
            result.is_valid = False
            result.allowed_files_valid = False
            unauth_list = sorted(list(unauthorized_files))
            result.errors.append(
                f"Patch modifies files outside plan.allowed_files scope: {unauth_list}"
            )

        # 2. Patch Change Budget Check
        if len(patch.files_changed) > self.max_files:
            result.is_valid = False
            result.budget_valid = False
            result.errors.append(
                f"Files changed count ({len(patch.files_changed)}) exceeds limit ({self.max_files})"
            )

        if len(patch.hunks) > self.max_hunks:
            result.is_valid = False
            result.budget_valid = False
            result.errors.append(
                f"Hunks count ({len(patch.hunks)}) exceeds limit ({self.max_hunks})"
            )

        total_lines_added = 0
        for hunk in patch.hunks:
            target = hunk.target_symbol
            lines = target.replacement_code.splitlines()
            total_lines_added += len(lines)

        if total_lines_added > self.max_added_lines:
            result.is_valid = False
            result.budget_valid = False
            result.errors.append(
                f"Total lines added ({total_lines_added}) exceeds limit ({self.max_added_lines})"
            )

        # 3. Source Existence & Content Hash Check
        for hunk in patch.hunks:
            target = hunk.target_symbol
            file_path = self.repo_root / target.file_path

            if not file_path.exists():
                result.is_valid = False
                result.hashes_valid = False
                result.errors.append(f"Target file does not exist: {target.file_path}")
                continue

            if target.expected_content_hash:
                current_code = file_path.read_text(encoding="utf-8")
                current_hash = SymbolTarget.compute_hash(current_code)
                if current_hash != target.expected_content_hash:
                    result.is_valid = False
                    result.hashes_valid = False
                    result.errors.append(
                        f"Hash mismatch for {target.file_path}! "
                        f"Expected: {target.expected_content_hash}, Got: {current_hash}"
                    )

        # 4. AST Syntax Verification
        for hunk in patch.hunks:
            target = hunk.target_symbol
            if target.file_path.endswith(".py"):
                try:
                    ast.parse(target.replacement_code, filename=target.file_path)
                except SyntaxError as e:
                    result.is_valid = False
                    result.syntax_valid = False
                    result.errors.append(
                        f"AST Syntax error in proposed patch for {target.file_path}: {e}"
                    )

        return result
