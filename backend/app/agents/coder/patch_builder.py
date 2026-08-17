"""
Phase 9A: Patch Builder & Replacement Engine
"""

from pathlib import Path

from app.agents.coder.models import CodePatch, SymbolTarget


class PatchApplicationError(Exception):
    """Raised when patch application fails due to hash mismatch or missing file."""


class PatchBuilder:
    """Applies symbol replacements safely to target files within working tree or worktree."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)

    def apply_patch(self, patch: CodePatch, verify_hash: bool = True) -> list[str]:
        """Applies CodePatch hunks to disk and returns list of modified file paths."""
        modified_files: list[str] = []

        for hunk in patch.hunks:
            target = hunk.target_symbol
            file_path = self.repo_root / target.file_path

            if not file_path.exists():
                raise PatchApplicationError(f"Target file does not exist: {target.file_path}")

            original_code = file_path.read_text(encoding="utf-8")

            if verify_hash and target.expected_content_hash:
                current_hash = SymbolTarget.compute_hash(original_code)
                if current_hash != target.expected_content_hash:
                    raise PatchApplicationError(
                        f"Hash mismatch for {target.file_path}! "
                        f"Expected: {target.expected_content_hash}, Got: {current_hash}"
                    )

            # Apply replacement
            file_path.write_text(target.replacement_code, encoding="utf-8")
            if target.file_path not in modified_files:
                modified_files.append(target.file_path)

        return modified_files
