"""
Multi-signal evidence scoring engine for repository candidate files.
"""

import ast
import re
from pathlib import Path

from app.agents.candidate.models import CandidateScore


class CandidateScorer:
    """Scores repository files using tracebacks, AST definitions, rip-grep, and git diff."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()

    def score_repository(self, issue_prompt: str) -> list[CandidateScore]:
        """Calculates multi-signal scores across all python files in the repository."""
        scores_map: dict[str, CandidateScore] = {}
        issue_lower = issue_prompt.lower()

        # 1. Tracebacks / Explicit path matches (500 / 300 pts)
        path_matches = re.findall(r"([a-zA-Z0-9_\-\/\\]+\.py)", issue_prompt)
        for pm in path_matches:
            normalized = pm.replace("\\", "/").lstrip("/")
            if (self.repo_root / normalized).exists():
                score_obj = scores_map.setdefault(normalized, CandidateScore(file_path=normalized))
                score_obj.explicit_path_score += 300
                score_obj.traceback_score += 500

        # Scan python files in repo
        for py_file in self.repo_root.glob("**/*.py"):
            try:
                rel_path = str(py_file.relative_to(self.repo_root)).replace("\\", "/")
            except ValueError:
                continue

            if any(
                part in rel_path
                for part in (".venv", "venv", ".git", ".forge_jobs", "site-packages", "__pycache__")
            ):
                continue

            score_obj = scores_map.setdefault(rel_path, CandidateScore(file_path=rel_path))

            # Check filename keyword matches
            file_name = py_file.stem.lower()
            if file_name and file_name in issue_lower:
                score_obj.explicit_path_score += 150

            # 2. AST parsing & symbol matching
            try:
                raw_code = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(raw_code)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name.lower() in issue_lower:
                            score_obj.symbol_match_score += 100
            except (SyntaxError, IndentationError):
                score_obj.ast_error_score += 200
            except Exception:
                pass

        # Sort candidate scores descending
        sorted_scores = sorted(scores_map.values(), key=lambda s: s.total_score, reverse=True)
        return sorted_scores
