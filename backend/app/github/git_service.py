"""
Phase 10B: Pure Local Git Branch & Conventional Commit Service
Manages local git feature branch creation, conventional commit formatting, staging, and pushing.
"""

import logging
import os
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from app.agents.coder.models import CodePatch
from app.agents.plan_models import ImplementationPlan
from app.github.auth import GitHubAuthManager
from app.github.git_remote import (
    DEFAULT_TOKEN_HOSTS,
    RemoteInfo,
    parse_remote_url,
    redact_credentials,
    token_auth_env,
)

logger = logging.getLogger(__name__)

FORGE_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "Forge Agent Engine",
    "GIT_AUTHOR_EMAIL": "forge-agent@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "Forge Agent Engine",
    "GIT_COMMITTER_EMAIL": "forge-agent@users.noreply.github.com",
}


class GitError(RuntimeError):
    """Raised when a git command fails. Messages are credential-redacted."""


class GitService:
    """Provides pure git operations without external GitHub API dependencies."""

    def __init__(
        self,
        repo_root: str | Path,
        token_provider: Callable[[], str | None] | None = None,
        token_hosts: Iterable[str] = DEFAULT_TOKEN_HOSTS,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._token_provider = token_provider or GitHubAuthManager.get_token
        # The GitHub token is only ever sent to these hosts (add GHE hosts explicitly).
        self._token_hosts = frozenset(h.casefold() for h in token_hosts)

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def _git(
        self, args: list[str], extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **extra_env} if extra_env else None
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )

    def _run_git(self, args: list[str], extra_env: dict[str, str] | None = None) -> str:
        """Runs git and returns stdout; raises GitError on a non-zero exit.

        Only the subcommand is logged — arguments may carry commit messages or paths.
        """
        res = self._git(args, extra_env)
        if res.returncode != 0:
            err_msg = redact_credentials((res.stderr or res.stdout or "").strip())
            logger.error(f"git {args[0]} failed: {err_msg}")
            raise GitError(f"git {args[0]} failed: {err_msg}")
        return res.stdout.strip()

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def current_branch(self) -> str | None:
        """Current branch name, or None when HEAD is detached."""
        return self._git(["symbolic-ref", "--short", "-q", "HEAD"]).stdout.strip() or None

    def current_ref(self) -> str:
        """Current branch name, or the commit SHA when HEAD is detached."""
        return self.current_branch() or self._run_git(["rev-parse", "HEAD"])

    def checkout(self, ref: str) -> None:
        self._run_git(["checkout", ref])

    def create_feature_branch(self, job_id: str) -> str:
        """Creates and checks out a new 'forge/issue-<job_id>' branch from HEAD.

        Never resets an existing branch: raises GitError if the name is taken.
        """
        branch_name = f"forge/issue-{job_id[:8]}"
        if self._git(["rev-parse", "--verify", "-q", f"refs/heads/{branch_name}"]).returncode == 0:
            raise GitError(f"Branch {branch_name} already exists; refusing to overwrite it.")
        self._run_git(["checkout", "-b", branch_name])
        logger.info(f"Created feature branch: {branch_name}")
        return branch_name

    def default_base_branch(self, remote_name: str = "origin") -> str:
        """The remote's default branch (from <remote>/HEAD), falling back to 'main'."""
        ref = self._git(["symbolic-ref", "--short", "-q", f"refs/remotes/{remote_name}/HEAD"])
        return ref.stdout.strip().removeprefix(f"{remote_name}/") or "main"

    def delete_branch(self, branch_name: str) -> None:
        self._run_git(["branch", "-D", branch_name])

    # ------------------------------------------------------------------
    # Working tree
    # ------------------------------------------------------------------

    def dirty_paths(self, paths: Iterable[str]) -> list[str]:
        """Paths (of those given) with uncommitted, untracked, or gitignored local content.

        Ignored files count too: they hold user data that discard_paths would delete.
        """
        path_list = sorted(set(paths))
        if not path_list:
            return []
        res = self._git(
            [
                "status",
                "--porcelain",
                "-z",
                "--untracked-files=all",
                "--ignored=matching",
                "--",
                *path_list,
            ]
        )
        if res.returncode != 0:
            raise GitError(f"git status failed: {redact_credentials(res.stderr.strip())}")

        # -z entries are "XY <path>\0"; renames/copies add the original path as an extra entry.
        entries = res.stdout.split("\0")
        dirty: list[str] = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            if entry:
                dirty.append(entry[3:])
                if entry[0] in "RC":
                    i += 1
            i += 1
        return dirty

    def discard_paths(self, paths: Iterable[str]) -> None:
        """Restores the given paths to HEAD, deleting ones HEAD does not track.

        Only safe for paths that were clean beforehand (see dirty_paths).
        """
        for rel_path in sorted(set(paths)):
            self._git(["reset", "-q", "--", rel_path])
            tracked = self._git(["cat-file", "-e", f"HEAD:{rel_path}"]).returncode == 0
            if tracked:
                self._run_git(["checkout", "HEAD", "--", rel_path])
            else:
                (self.repo_root / rel_path).unlink(missing_ok=True)

    def show_commit(self, ref: str) -> str:
        """Returns the patch introduced by a commit, or "" if it cannot be read."""
        try:
            return self._run_git(["show", "--format=", ref])
        except GitError:
            return ""

    def get_working_tree_diff(self) -> str:
        """Returns physical 'git diff' string for current working tree / staged changes."""
        try:
            diff = self._run_git(["diff", "HEAD"])
            if not diff.strip():
                diff = self._run_git(["diff"])
            return diff
        except GitError:
            return ""

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------

    def format_conventional_commit(
        self,
        plan: ImplementationPlan,
        patch: CodePatch,
    ) -> str:
        """Formats a conventional commit message from plan and patch."""
        summary = plan.summary or "Resolve repository issue"
        clean_summary = summary.replace("\n", " ").strip()
        if len(clean_summary) > 70:
            clean_summary = clean_summary[:67] + "..."

        lines = [
            f"fix(core): {clean_summary}",
            "",
            "Files Changed:",
        ]
        for f in sorted(set(patch.files_changed)):
            lines.append(f"  - {f}")
        lines.append("")
        lines.append("Generated by Forge Agent Engine")
        return "\n".join(lines)

    def _identity_env(self) -> dict[str, str]:
        """Forge's commit identity, used only when the repo has none configured.

        Passed via environment so the user's git config is never modified.
        """
        has_identity = all(
            self._git(["config", key]).stdout.strip() for key in ("user.name", "user.email")
        )
        return {} if has_identity else dict(FORGE_IDENTITY_ENV)

    def commit_patch(
        self,
        plan: ImplementationPlan,
        patch: CodePatch,
    ) -> str:
        """Stages and commits exactly the patch's files; returns the new commit SHA.

        Other local changes — staged or not — are left out of the commit.
        Raises GitError if staging or committing fails or the patch changed nothing.
        """
        paths = sorted(set(patch.files_changed))
        if not paths:
            raise GitError("Patch lists no files to commit.")

        self._run_git(["add", "-A", "--", *paths])
        if not self._run_git(["diff", "--cached", "--name-only", "--", *paths]):
            raise GitError("Patch produced no changes to commit.")

        commit_msg = self.format_conventional_commit(plan, patch)
        self._run_git(
            ["commit", "-m", commit_msg, "--only", "--", *paths],
            extra_env=self._identity_env(),
        )
        return self._run_git(["rev-parse", "HEAD"])

    # ------------------------------------------------------------------
    # Remotes
    # ------------------------------------------------------------------

    def _remote_info(self, remote_name: str = "origin") -> RemoteInfo | None:
        res = self._git(["remote", "get-url", remote_name])
        return parse_remote_url(res.stdout) if res.returncode == 0 else None

    def _push_auth_env(self, remote: RemoteInfo | None) -> dict[str, str] | None:
        """Token env for trusted https GitHub hosts only; everything else uses the
        user's own credential helper or ssh setup."""
        if not remote or remote.scheme != "https":
            return None
        if remote.host.casefold() not in self._token_hosts:
            return None
        token = self._token_provider()
        return token_auth_env(remote, token, os.environ) if token else None

    def push_to_remote(self, branch_name: str, remote_name: str = "origin") -> None:
        """Pushes the branch to the named remote. Raises GitError on failure.

        A GitHub token is supplied through environment-scoped git config — never the
        URL — and only to hosts in token_hosts.
        """
        auth_env = self._push_auth_env(self._remote_info(remote_name))
        self._run_git(["push", "-u", remote_name, branch_name], extra_env=auth_env)

    def get_remote_owner_repo(self) -> tuple[str, str]:
        """Parses owner and repo name from the origin remote URL."""
        remote = self._remote_info()
        if remote:
            return remote.owner, remote.repo
        return "local", self.repo_root.name
