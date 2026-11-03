"""
Repository path containment for LLM-proposed patch targets.

Every file path in a patch comes from model output, so it is untrusted: it must be a
relative path that stays inside the repository after resolving `..` and symlinks, and
must never reach git internals — on case-insensitive filesystems too.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath

FORBIDDEN_DIR_NAMES = frozenset({".git"})


class UnsafePathError(ValueError):
    """Raised when a patch path is absolute, escapes the repository, or targets git internals."""


def _is_forbidden(part: str) -> bool:
    # casefold: `.GIT` is `.git` on macOS/Windows; strip: NTFS ignores trailing dots/spaces.
    return part.rstrip(". ").casefold() in FORBIDDEN_DIR_NAMES


def resolve_in_repo(repo_root: str | Path, rel_path: str) -> Path:
    """Returns the absolute path for rel_path, guaranteed to live inside repo_root.

    Raises UnsafePathError for empty, absolute, drive-qualified, escaping, control-character,
    or git-internal paths — checked on both the given path and the symlink-resolved one.
    """
    if not rel_path or not rel_path.strip():
        raise UnsafePathError("Empty file path in patch.")
    if any(ord(ch) < 32 for ch in rel_path):
        raise UnsafePathError(f"Control character in patch path: {rel_path!r}")

    if (
        PurePosixPath(rel_path).is_absolute()
        or PureWindowsPath(rel_path).is_absolute()
        or PureWindowsPath(rel_path).drive
    ):
        raise UnsafePathError(f"Absolute path not allowed in patch: {rel_path}")

    root = Path(repo_root).resolve()
    try:
        candidate = (root / rel_path).resolve()
    except (OSError, ValueError) as e:
        raise UnsafePathError(f"Unresolvable patch path {rel_path!r}: {e}") from e

    if not candidate.is_relative_to(root):
        raise UnsafePathError(f"Path escapes the repository: {rel_path}")

    given_parts = PurePosixPath(rel_path.replace("\\", "/")).parts
    resolved_parts = candidate.relative_to(root).parts
    if any(_is_forbidden(p) for p in (*given_parts, *resolved_parts)):
        raise UnsafePathError(f"Patch may not modify git internals: {rel_path}")

    return candidate
