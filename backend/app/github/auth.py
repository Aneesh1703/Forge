import os
import subprocess
from abc import ABC, abstractmethod

from app.cli.config import ConfigManager


class GitHubAuthProvider(ABC):
    """Abstract authentication provider interface for GitHub API interactions."""

    @abstractmethod
    def get_token(self) -> str | None:
        """Retrieves a valid GitHub API OAuth/Bearer token."""
        pass


class ConfigManagerAuth(GitHubAuthProvider):
    """Retrieves GitHub token from ConfigManager (OS Keyring / Vault)."""

    def get_token(self) -> str | None:
        return ConfigManager.get_key("github")


class EnvironmentTokenAuth(GitHubAuthProvider):
    """Retrieves GitHub token from GITHUB_TOKEN or GH_TOKEN environment variables."""

    def get_token(self) -> str | None:
        return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")


class GitHubCLIAuth(GitHubAuthProvider):
    """Retrieves GitHub token by querying the local 'gh' CLI credentials."""

    def get_token(self) -> str | None:
        try:
            res = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            token = res.stdout.strip()
            return token if token else None
        except Exception:
            return None


class CompositeGitHubAuth(GitHubAuthProvider):
    """Tries ConfigManager (keyring) first, then env vars,
    falling back to local 'gh' CLI token."""

    def __init__(self) -> None:
        self.providers: list[GitHubAuthProvider] = [
            ConfigManagerAuth(),
            EnvironmentTokenAuth(),
            GitHubCLIAuth(),
        ]

    def get_token(self) -> str | None:
        for provider in self.providers:
            token = provider.get_token()
            if token:
                return token
        return None


class GitHubAuthManager:
    """Helper service for verifying GitHub auth status and onboarding guidance."""

    @classmethod
    def is_authenticated(cls) -> bool:
        return CompositeGitHubAuth().get_token() is not None

    @classmethod
    def is_gh_cli_installed(cls) -> bool:
        try:
            res = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False
