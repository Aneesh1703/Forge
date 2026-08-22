"""
Phase 9A: Patch Builder & Surgical AST Replacement Engine
"""

import ast
import textwrap
from pathlib import Path

from app.agents.coder.models import CodePatch, SymbolAction, SymbolTarget


class PatchApplicationError(Exception):
    """Raised when patch application fails due to hash mismatch or missing file."""


class PatchBuilder:
    """Applies symbol replacements surgically to target files using AST nodes and content hashes."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def _apply_modify(self, original_code: str, target: SymbolTarget) -> str:
        """MODIFY: Surgical AST node or anchor snippet line-range replacement."""
        if not original_code.strip():
            return target.replacement_code.rstrip() + "\n"

        symbol_name = target.qualified_symbol_name
        replacement_code = target.replacement_code
        original_snippet = target.original_snippet

        # 1. Header line block replacement: If header exists, replace in-place!
        rep_lines = [ln.strip() for ln in replacement_code.splitlines() if ln.strip()]
        if rep_lines:
            first_rep_line = rep_lines[0]
            # Avoid matching generic lines like 'try:', 'else:', 'pass'
            if len(first_rep_line) > 10 and first_rep_line in original_code:
                pos = original_code.find(first_rep_line)
                if pos != -1:
                    # Find start of matching line
                    line_start = original_code.rfind("\n", 0, pos)
                    line_start = 0 if line_start == -1 else line_start + 1

                    # Extract target line leading indentation
                    target_line = original_code[line_start:].splitlines()[0]
                    target_indent_str = target_line[: len(target_line) - len(target_line.lstrip())]
                    target_indent_len = len(target_indent_str)

                    # Determine full end boundary of original block
                    orig_lines = original_code[line_start:].splitlines(keepends=True)
                    block_end_offset = len(orig_lines[0])

                    for line in orig_lines[1:]:
                        stripped = line.strip()
                        if not stripped:
                            block_end_offset += len(line)
                            continue
                        indent_len = len(line) - len(line.lstrip())
                        if indent_len > target_indent_len or (
                            indent_len == target_indent_len
                            and stripped.startswith(
                                ("else:", "elif ", "except ", "finally:", "col", "with st.", "st.")
                            )
                        ):
                            block_end_offset += len(line)
                        else:
                            break

                    block_end_idx = line_start + block_end_offset

                    # Re-indent replacement code to match target indentation
                    indented_replacement = textwrap.indent(
                        textwrap.dedent(replacement_code.rstrip()), target_indent_str
                    )
                    return (
                        original_code[:line_start]
                        + indented_replacement
                        + "\n"
                        + original_code[block_end_idx:]
                    )

        # 2. Try AST node line-range matching by symbol name (Functions, Classes, Variables)
        ignored_symbols = ("auto_detected", "module", "<module>", "<module-level>", "file", "root")
        if symbol_name and symbol_name.lower() not in ignored_symbols:
            try:
                tree = ast.parse(original_code)
                lines = original_code.splitlines(keepends=True)
                target_node: ast.AST | None = None

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name == symbol_name or f".{node.name}" in symbol_name:
                            target_node = node
                            break
                    elif isinstance(node, ast.Assign):
                        for target_expr in node.targets:
                            if isinstance(target_expr, ast.Name) and target_expr.id == symbol_name:
                                target_node = node
                                break
                        if target_node:
                            break

                if (
                    target_node
                    and hasattr(target_node, "lineno")
                    and hasattr(target_node, "end_lineno")
                ):
                    # If replacement is a new function/class definition anchored at a symbol
                    prefix = ("def ", "class ", "async def ")
                    is_new_def = replacement_code.strip().startswith(prefix)
                    if is_new_def and symbol_name not in replacement_code:
                        target.anchor_symbol = symbol_name
                        return self._apply_add(original_code, target)

                    start_idx = getattr(target_node, "lineno") - 1
                    end_idx = getattr(target_node, "end_lineno")

                    before = "".join(lines[:start_idx])
                    after = "".join(lines[end_idx:])
                    new_replacement = replacement_code.rstrip() + "\n"
                    return before + new_replacement + after
            except Exception:
                pass

        # 3. Try exact original_snippet replacement
        if original_snippet and original_snippet.strip() in original_code:
            snippet_match = original_snippet.strip()
            # Replace first exact occurrence cleanly
            pos = original_code.find(snippet_match)
            if pos != -1:
                return (
                    original_code[:pos]
                    + replacement_code.rstrip()
                    + "\n"
                    + original_code[pos + len(snippet_match) :]
                )

        # 4. Top-level full module replacement (Only when explicitly targeting full module)
        if symbol_name and symbol_name.lower() in ("<module>", "<module-level>"):
            starts_valid = replacement_code.strip().startswith(
                ("import ", "from ", "#", "def ", "class ")
            )
            if len(replacement_code) > 0.7 * len(original_code) and starts_valid:
                return replacement_code.rstrip() + "\n"

        # 5. Smart AST insertion fallback for import statements and synthetic module anchors
        is_import_code = replacement_code.strip().startswith(("import ", "from "))
        keywords = ("import", "export", "top_level", "module_import")
        is_synthetic_import = any(kw in (symbol_name or "").lower() for kw in keywords)
        is_ignored_symbol = bool(symbol_name and symbol_name.lower() in ignored_symbols)

        if is_import_code or is_synthetic_import or is_ignored_symbol or target.anchor_symbol:
            return self._apply_add(original_code, target)

        # STRICT REJECTION: If code block cannot be mapped or anchored safely
        raise PatchApplicationError(
            f"Target symbol '{symbol_name}' and anchor snippet could not be resolved in "
            f"{target.file_path}. Specify valid anchor_symbol or original_snippet."
        )

    def _apply_add(self, original_code: str, target: SymbolTarget) -> str:
        """ADD: Insert new symbol at explicit anchor position without touching existing code."""
        if not original_code.strip():
            return target.replacement_code.rstrip() + "\n"

        replacement_code = target.replacement_code
        anchor_symbol = target.anchor_symbol
        anchor_position = target.anchor_position or "after"
        original_snippet = target.original_snippet

        lines = original_code.splitlines(keepends=True)

        # 0. Handle top-level import insertions cleanly
        is_import_code = replacement_code.strip().startswith(("import ", "from "))
        qual_name = (target.qualified_symbol_name or "").lower()
        anchor_name = (anchor_symbol or "").lower()
        is_synthetic_import = is_import_code or any(
            kw in qual_name or kw in anchor_name for kw in ("import", "export", "module")
        )

        if is_synthetic_import:
            clean_rep = textwrap.dedent(replacement_code.rstrip()) + "\n"
            try:
                tree = ast.parse(original_code)
                last_import_line = 0
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        end_l = getattr(node, "end_lineno", None)
                        if isinstance(end_l, int) and end_l > last_import_line:
                            last_import_line = end_l

                if last_import_line > 0:
                    before = "".join(lines[:last_import_line])
                    after = "".join(lines[last_import_line:])
                    return before + clean_rep + after
                else:
                    return clean_rep + original_code
            except Exception:
                pass

        # 1. Try explicit anchor symbol match in AST
        if anchor_symbol:
            try:
                tree = ast.parse(original_code)
                anchor_node: ast.AST | None = None

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name == anchor_symbol or f".{node.name}" in anchor_symbol:
                            anchor_node = node
                            break

                if (
                    anchor_node
                    and hasattr(anchor_node, "lineno")
                    and hasattr(anchor_node, "end_lineno")
                ):
                    anchor_lineno: int = getattr(anchor_node, "lineno")
                    anchor_end_lineno: int = getattr(anchor_node, "end_lineno")
                    if anchor_position == "before":
                        idx = anchor_lineno - 1
                    else:  # "after"
                        idx = anchor_end_lineno

                    before = "".join(lines[:idx])
                    after = "".join(lines[idx:])
                    return before + "\n" + replacement_code.rstrip() + "\n\n" + after
            except Exception:
                pass

        # 2. Try original_snippet anchor match
        if original_snippet and original_snippet.strip() in original_code:
            match_str = original_snippet.strip()
            pos = original_code.find(match_str)
            if pos != -1:
                if anchor_position == "before":
                    return (
                        original_code[:pos]
                        + replacement_code.rstrip()
                        + "\n\n"
                        + original_code[pos:]
                    )
                else:
                    end_pos = pos + len(match_str)
                    return (
                        original_code[:end_pos]
                        + "\n\n"
                        + replacement_code.rstrip()
                        + original_code[end_pos:]
                    )

        # 3. Fallback: Insert after last top-level function or import definition (Python files)
        if target.file_path.endswith(".py"):
            try:
                tree = ast.parse(original_code)
                last_def_end = 0
                for node in ast.walk(tree):
                    valid_types = (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                        ast.ClassDef,
                        ast.Import,
                        ast.ImportFrom,
                    )
                    if isinstance(node, valid_types):
                        end_line = getattr(node, "end_lineno", None)
                        if isinstance(end_line, int) and end_line > last_def_end:
                            last_def_end = end_line

                if last_def_end > 0:
                    before = "".join(lines[:last_def_end])
                    after = "".join(lines[last_def_end:])
                    return before + "\n\n" + replacement_code.rstrip() + "\n" + after
            except Exception:
                pass
        else:
            # For non-Python text files (e.g. requirements.txt, .json, .md, .txt), append cleanly
            base = original_code.rstrip()
            rep = replacement_code.strip()
            if rep and rep not in base:
                return base + "\n" + rep + "\n" if base else rep + "\n"
            return original_code

        # STRICT REJECTION: Failed to resolve anchor location safely
        raise PatchApplicationError(
            f"Failed to resolve anchor position for ADD action in {target.file_path}. "
            "Specify valid anchor_symbol or original_snippet."
        )

    def _apply_delete(self, original_code: str, symbol_name: str) -> str:
        """DELETE: Remove exact AST node line-range from file."""
        if not original_code.strip():
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
                return before + after
        except Exception:
            pass

        raise PatchApplicationError(f"Could not find symbol '{symbol_name}' to DELETE.")

    def apply_patch(self, patch: CodePatch, verify_hash: bool = False) -> list[str]:
        """Applies CodePatch hunks surgically to target files and returns modified file paths."""
        modified_files: list[str] = []

        for hunk in patch.hunks:
            target = hunk.target_symbol
            file_path = self.repo_root / target.file_path

            if hunk.action == SymbolAction.REPLACE_FILE:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(target.replacement_code.rstrip() + "\n", encoding="utf-8")
                if target.file_path not in modified_files:
                    modified_files.append(target.file_path)
                continue

            if not file_path.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
                original_code = ""
            else:
                original_code = file_path.read_text(encoding="utf-8", errors="replace")

            if verify_hash and target.expected_content_hash:
                current_hash = SymbolTarget.compute_hash(original_code)
                if current_hash != target.expected_content_hash:
                    raise PatchApplicationError(
                        f"Hash mismatch for {target.file_path}! "
                        f"Expected: {target.expected_content_hash}, Got: {current_hash}"
                    )

            if hunk.action == SymbolAction.ADD:
                new_code = self._apply_add(original_code, target)
            elif hunk.action == SymbolAction.DELETE:
                new_code = self._apply_delete(original_code, target.qualified_symbol_name)
            else:  # SymbolAction.MODIFY
                new_code = self._apply_modify(original_code, target)

            file_path.write_text(new_code, encoding="utf-8")
            if target.file_path not in modified_files:
                modified_files.append(target.file_path)

        return modified_files
