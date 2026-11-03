"""
Repository file listing — the single source of truth for "which files exist".

Planning agents validate every path they propose against this listing, so nothing is
ever guessed into existence.
"""

import os
import subprocess
from pathlib import Path, PurePosixPath

# Never part of the user's code: VCS internals, environments, caches, Forge's own state.
SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".forge_jobs",
        ".forge_worktrees",
    }
)


def list_repo_files(root: str | Path) -> frozenset[str]:
    """Repo-relative POSIX paths of every existing file that is tracked or untracked-but-
    not-ignored. Uses git when available, otherwise walks the tree skipping SKIPPED_DIRS.
    """
    root_path = Path(root).resolve()
    listed = _git_files(root_path)
    if listed is None:
        listed = _walk_files(root_path)
    return frozenset(
        p
        for p in listed
        if not SKIPPED_DIRS.intersection(PurePosixPath(p).parts) and (root_path / p).is_file()
    )


def _git_files(root: Path) -> list[str] | None:
    try:
        res = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if res.returncode != 0:
        return None
    return [p for p in res.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIPPED_DIRS]
        rel_dir = Path(dirpath).relative_to(root)
        files.extend((rel_dir / name).as_posix() for name in filenames)
    return files


def is_test_path(path: str) -> bool:
    """True for files pytest collects by default: test_*.py or *_test.py."""
    name = PurePosixPath(path.replace("\\", "/")).name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))
