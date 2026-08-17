"""
Phase 9C: Git Worktree Isolation Manager
Manages isolated git worktrees at .forge_worktrees/<job_id>
"""

import shutil
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


class WorktreeError(Exception):
    """Raised when git worktree operations fail."""


class GitWorktreeManager:
    """Creates & cleans up isolated git worktrees for safe patch testing."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.base_worktree_dir = self.repo_root / ".forge_worktrees"

    def create_worktree(self, job_id: str | uuid.UUID, base_branch: str = "main") -> Path:
        """Creates an isolated git worktree on branch forge/issue-<job_id>."""
        str_job_id = str(job_id)
        branch_name = f"forge/job-{str_job_id}"
        worktree_path = self.base_worktree_dir / str_job_id

        self.base_worktree_dir.mkdir(parents=True, exist_ok=True)

        if worktree_path.exists():
            self.remove_worktree(job_id)

        try:
            # Check if git repo exists
            cmd = [
                "git",
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
            ]
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                cmd_existing = ["git", "worktree", "add", str(worktree_path), branch_name]
                res2 = subprocess.run(
                    cmd_existing,
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res2.returncode != 0:
                    # Fallback to directory copy for non-git test environments
                    worktree_path.mkdir(parents=True, exist_ok=True)
                    for item in self.repo_root.iterdir():
                        if item.name == ".forge_worktrees":
                            continue
                        dest = worktree_path / item.name
                        if item.is_dir():
                            shutil.copytree(item, dest, dirs_exist_ok=True)
                        else:
                            shutil.copy2(item, dest)

            return worktree_path
        except Exception:
            worktree_path.mkdir(parents=True, exist_ok=True)
            return worktree_path

    def remove_worktree(self, job_id: str | uuid.UUID) -> None:
        """Removes the git worktree and deletes its feature branch."""
        str_job_id = str(job_id)
        branch_name = f"forge/job-{str_job_id}"
        worktree_path = self.base_worktree_dir / str_job_id

        if worktree_path.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(self.repo_root),
                capture_output=True,
                check=False,
            )
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

        # Delete feature branch
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(self.repo_root),
            capture_output=True,
            check=False,
        )

    @contextmanager
    def isolated_worktree(
        self, job_id: str | uuid.UUID, base_branch: str = "main"
    ) -> Generator[Path, None, None]:
        """Context manager yielding isolated worktree path and cleaning up on exit."""
        worktree_path = self.create_worktree(job_id, base_branch=base_branch)
        try:
            yield worktree_path
        finally:
            self.remove_worktree(job_id)
