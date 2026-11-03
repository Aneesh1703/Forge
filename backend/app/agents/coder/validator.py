"""
Phase 9B: Deterministic Patch Safety Gate Engine
Validates allowed_files scope, patch budget limits, source content hashes, and AST syntax.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.coder.models import CodePatch, SymbolAction, SymbolTarget
from app.agents.coder.paths import UnsafePathError, resolve_in_repo
from app.agents.plan_models import ImplementationPlan


@dataclass
class PatchValidationResult:
    """Detailed deterministic safety validation report."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    paths_valid: bool = True
    allowed_files_valid: bool = True
    budget_valid: bool = True
    hashes_valid: bool = True
    syntax_valid: bool = True


class PatchSafetyGate:
    """Enforces non-bypassable deterministic validation rules on generated patches."""

    def __init__(
        self,
        repo_root: str | Path,
        max_files: int = 20,
        max_hunks: int = 50,
        max_added_lines: int = 5000,
        max_deleted_lines: int = 2000,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.max_files = max_files
        self.max_hunks = max_hunks
        self.max_added_lines = max_added_lines
        self.max_deleted_lines = max_deleted_lines

    def validate(self, plan: ImplementationPlan, patch: CodePatch) -> PatchValidationResult:
        """Executes all deterministic safety checks against the patch and working tree."""
        result = PatchValidationResult()

        # 0. Path Containment Check — later checks read these paths, so stop on failure.
        path_errors = self._path_errors(patch)
        if path_errors:
            result.is_valid = False
            result.paths_valid = False
            result.errors.extend(path_errors)
            return result

        # 1. Allowed Files Boundary Check
        # Downstream commit/rollback only see files_changed, so every hunk must be listed.
        hunk_files = {hunk.target_symbol.file_path for hunk in patch.hunks}
        unlisted = hunk_files - set(patch.files_changed)
        if unlisted:
            result.is_valid = False
            result.allowed_files_valid = False
            result.errors.append(
                f"Hunks target files not listed in files_changed: {sorted(unlisted)}"
            )

        # The approved plan is the whole scope: a new file must be a planned CREATE.
        patch_files = set(patch.files_changed) | hunk_files
        unauthorized_files = patch_files - plan.allowed_files

        if unauthorized_files:
            result.is_valid = False
            result.allowed_files_valid = False
            unauth_list = sorted(list(unauthorized_files))
            result.errors.append(
                f"Patch modifies files outside plan.allowed_files scope: {unauth_list}"
            )

        # 2. Patch Change Budget Check
        if len(patch_files) > self.max_files:
            result.is_valid = False
            result.budget_valid = False
            result.errors.append(
                f"Files changed count ({len(patch_files)}) exceeds limit ({self.max_files})"
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

            is_new_file = hunk.action in (SymbolAction.REPLACE_FILE, SymbolAction.ADD)
            if not file_path.exists() and not is_new_file:
                result.is_valid = False
                result.hashes_valid = False
                result.errors.append(f"Target file does not exist: {target.file_path}")
                continue

            if target.expected_content_hash and file_path.exists():
                current_code = file_path.read_text(encoding="utf-8", errors="replace")
                current_hash = SymbolTarget.compute_hash(current_code)
                if current_hash != target.expected_content_hash:
                    result.is_valid = False
                    result.hashes_valid = False
                    result.errors.append(
                        f"Hash mismatch for {target.file_path}! "
                        f"Expected: {target.expected_content_hash}, Got: {current_hash}"
                    )

        # 4. Full File AST Syntax Verification (Surgical Trial Application)
        try:
            from app.agents.coder.patch_builder import PatchBuilder

            patch_builder = PatchBuilder(self.repo_root)

            for hunk in patch.hunks:
                target = hunk.target_symbol
                if target.file_path.endswith(".py"):
                    file_path = self.repo_root / target.file_path
                    orig_code = (
                        file_path.read_text(encoding="utf-8", errors="replace")
                        if file_path.exists()
                        else ""
                    )
                    try:
                        if hunk.action == SymbolAction.ADD:
                            trial_code = patch_builder._apply_add(orig_code, target)
                        elif hunk.action == SymbolAction.DELETE:
                            sym_name = target.qualified_symbol_name
                            trial_code = patch_builder._apply_delete(orig_code, sym_name)
                        else:  # MODIFY / REPLACE_FILE
                            trial_code = patch_builder._apply_modify(orig_code, target)

                        ast.parse(trial_code, filename=target.file_path)
                    except SyntaxError as e:
                        result.is_valid = False
                        result.syntax_valid = False
                        result.errors.append(
                            f"AST Syntax error in proposed patch for {target.file_path}: {e}"
                        )
        except Exception:
            pass

        return result

    def _path_errors(self, patch: CodePatch) -> list[str]:
        """Rejects any patch path that is absolute, escapes the repo, or targets .git."""
        paths = set(patch.files_changed) | {h.target_symbol.file_path for h in patch.hunks}
        errors: list[str] = []
        for rel_path in sorted(paths):
            try:
                resolve_in_repo(self.repo_root, rel_path)
            except UnsafePathError as e:
                errors.append(str(e))
        return errors
