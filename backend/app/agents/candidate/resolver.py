"""
CandidateContextResolver engine for multi-file discovery and context preparation.
"""

from pathlib import Path

from app.agents.candidate.models import CandidateContext, CandidateFile
from app.agents.candidate.scoring import CandidateScorer


class CandidateContextResolver:
    """Discovers, scores, and resolves multi-file candidate contexts for LLM agents."""

    def __init__(self, repo_root: Path, max_candidates: int = 5) -> None:
        self.repo_root = repo_root.resolve()
        self.max_candidates = max_candidates
        self.scorer = CandidateScorer(self.repo_root)

    def resolve_candidates(self, issue_prompt: str) -> CandidateContext:
        """Resolves top candidate source files and matching test files for an issue."""
        all_scores = self.scorer.score_repository(issue_prompt)

        candidate_files: list[CandidateFile] = []
        test_files: list[CandidateFile] = []

        for score in all_scores:
            abs_p = self.repo_root / score.file_path
            if not abs_p.exists():
                continue

            is_test = "test" in score.file_path.lower()
            cf = CandidateFile(
                file_path=score.file_path,
                abs_path=abs_p,
                score=score,
                is_test_file=is_test,
            )

            if is_test:
                if len(test_files) < 2:
                    test_files.append(cf)
            else:
                if len(candidate_files) < self.max_candidates:
                    candidate_files.append(cf)

        # Fallback: if no candidates found, pick the first py file in the repo
        if not candidate_files:
            for py_file in self.repo_root.glob("**/*.py"):
                try:
                    rel_p = str(py_file.relative_to(self.repo_root)).replace("\\", "/")
                except ValueError:
                    continue
                if any(
                    part in rel_p
                    for part in (".venv", "venv", ".git", ".forge_jobs", "site-packages")
                ):
                    continue
                scores = self.scorer.score_repository(rel_p)
                score_obj = scores[0] if scores else None
                from app.agents.candidate.models import CandidateScore

                fallback_score = score_obj or CandidateScore(file_path=rel_p)
                cf = CandidateFile(
                    file_path=rel_p,
                    abs_path=py_file,
                    score=fallback_score,
                    is_test_file="test" in rel_p.lower(),
                )
                candidate_files.append(cf)
                break

        return CandidateContext(
            issue_prompt=issue_prompt,
            candidate_files=candidate_files,
            test_files=test_files,
        )
