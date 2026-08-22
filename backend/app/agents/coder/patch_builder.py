"""
Phase 9A: Patch Builder & Surgical AST Replacement Engine
"""

import ast
from pathlib import Path

from app.agents.coder.models import CodePatch, SymbolTarget


class PatchApplicationError(Exception):
    """Raised when patch application fails due to hash mismatch or missing file."""


class PatchBuilder:
    """Applies symbol replacements surgically to target files using AST nodes and content hashes."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def _replace_symbol_in_code(
        self, original_code: str, symbol_name: str, replacement_code: str
    ) -> str:
        """Surgically replaces a specific function or class symbol in original Python code."""
        if not symbol_name:
            if replacement_code not in original_code:
                return original_code.rstrip() + "\n\n" + replacement_code + "\n"
            return original_code

        try:
            tree = ast.parse(original_code)
            lines = original_code.splitlines(keepends=True)
            target_node: ast.AST | None = None

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol_name or f".{node.name}" in symbol_name:
                        target_node = node
                        break

            if (
                target_node
                and hasattr(target_node, "lineno")
                and hasattr(target_node, "end_lineno")
            ):
                start_idx = target_node.lineno - 1
                end_idx = target_node.end_lineno

                before = "".join(lines[:start_idx])
                after = "".join(lines[end_idx:])
                new_replacement = replacement_code.rstrip() + "\n"
                return before + new_replacement + after
        except Exception:
            pass

        if replacement_code not in original_code:
            return original_code.rstrip() + "\n\n" + replacement_code + "\n"
        return original_code

    def apply_patch(self, patch: CodePatch, verify_hash: bool = False) -> list[str]:
        """Applies CodePatch hunks surgically to target files and returns modified file paths."""
        modified_files: list[str] = []

        for hunk in patch.hunks:
            target = hunk.target_symbol
            file_path = self.repo_root / target.file_path

            if not file_path.exists():
                raise PatchApplicationError(f"Target file does not exist: {target.file_path}")

            original_code = file_path.read_text(encoding="utf-8", errors="replace")

            if verify_hash and target.expected_content_hash:
                current_hash = SymbolTarget.compute_hash(original_code)
                if current_hash != target.expected_content_hash:
                    raise PatchApplicationError(
                        f"Hash mismatch for {target.file_path}! "
                        f"Expected: {target.expected_content_hash}, Got: {current_hash}"
                    )

            new_code = self._replace_symbol_in_code(
                original_code, target.qualified_symbol_name, target.replacement_code
            )

            file_path.write_text(new_code, encoding="utf-8")
            if target.file_path not in modified_files:
                modified_files.append(target.file_path)

        return modified_files
