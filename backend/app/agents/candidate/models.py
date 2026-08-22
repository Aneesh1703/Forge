"""
Candidate context domain models and score tracking dataclasses.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CandidateScore:
    """Multi-signal evidence score for a repository file candidate."""

    file_path: str
    traceback_score: int = 0
    explicit_path_score: int = 0
    ast_error_score: int = 0
    symbol_match_score: int = 0
    ripgrep_score: int = 0
    git_diff_score: int = 0

    @property
    def total_score(self) -> int:
        return (
            self.traceback_score
            + self.explicit_path_score
            + self.ast_error_score
            + self.symbol_match_score
            + self.ripgrep_score
            + self.git_diff_score
        )


@dataclass
class CandidateFile:
    """Ranked file candidate enriched with score metadata."""

    file_path: str
    abs_path: Path
    score: CandidateScore
    is_test_file: bool = False


@dataclass
class CandidateContext:
    """Container holding ranked candidate files and relevant test files for an issue."""

    issue_prompt: str
    candidate_files: list[CandidateFile] = field(default_factory=list)
    test_files: list[CandidateFile] = field(default_factory=list)
