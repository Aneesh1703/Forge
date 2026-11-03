"""
Git remote parsing and credential handling.

Tokens are passed to git only through environment-scoped config, never embedded in a
remote URL, so they cannot leak into argv, logs, error messages, or `.git/config`.
"""

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_TOKEN_HOSTS = frozenset({"github.com"})

_SCP_LIKE_REMOTE = re.compile(r"^[\w.-]+@(?P<host>[^:/]+):(?P<path>.+)$")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)


@dataclass(frozen=True)
class RemoteInfo:
    """Parsed git remote location."""

    scheme: str  # "https", "http", or "ssh"
    host: str
    owner: str
    repo: str
    port: int | None = None

    @property
    def authority(self) -> str:
        """host[:port], as git uses it to match http.<url>.* config keys."""
        return f"{self.host}:{self.port}" if self.port else self.host


def parse_remote_url(url: str) -> RemoteInfo | None:
    """Parses https://, ssh://, and scp-like (git@host:owner/repo) remote URLs."""
    url = url.strip().rstrip("/").removesuffix(".git")
    port: int | None = None
    if "://" in url:
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError:
            return None
        scheme, host, path = parsed.scheme, parsed.hostname or "", parsed.path
    else:
        match = _SCP_LIKE_REMOTE.match(url)
        if not match:
            return None
        scheme, host, path = "ssh", match.group("host"), match.group("path")

    parts = [p for p in path.split("/") if p]
    if not host or len(parts) < 2:
        return None
    return RemoteInfo(scheme=scheme, host=host, owner=parts[-2], repo=parts[-1], port=port)


def token_auth_env(remote: RemoteInfo, token: str, base_env: Mapping[str, str]) -> dict[str, str]:
    """Environment that makes git send a token to one https remote for one command.

    Appends to any GIT_CONFIG_COUNT entries already in base_env instead of replacing them.
    """
    index = int(base_env.get("GIT_CONFIG_COUNT") or 0)
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": str(index + 1),
        f"GIT_CONFIG_KEY_{index}": f"http.https://{remote.authority}/.extraheader",
        f"GIT_CONFIG_VALUE_{index}": f"AUTHORIZATION: basic {basic}",
        "GIT_TERMINAL_PROMPT": "0",
    }


def redact_credentials(text: str) -> str:
    """Masks user:token@ segments in any URL inside text."""
    return _URL_CREDENTIALS.sub(r"\g<scheme>***@", text)
