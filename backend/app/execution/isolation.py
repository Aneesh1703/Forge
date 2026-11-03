"""
Process isolation for running untrusted, LLM-written test code.

Tests run with an allowlisted environment, so API keys and tokens in Forge's own
environment never reach them. On POSIX they also run in their own process group, so a
timeout — or cleanup after a normal exit — kills every process they spawned. On Windows
only the process tree still attached to the runner is killed (via taskkill /T); orphaned
grandchildren can survive. This is not a filesystem or network sandbox.
"""

import asyncio
import os
import re
import signal
import subprocess
import sys
from collections.abc import Mapping

SAFE_ENV_VARS = frozenset(
    {
        # Process basics
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "TZ",
        "LANG",
        "LANGUAGE",
        "TMPDIR",
        "TMP",
        "TEMP",
        # Windows essentials
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        # TLS trust stores and tool caches (needed to install test dependencies)
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "UV_CACHE_DIR",
        "UV_PYTHON",
        "UV_PYTHON_INSTALL_DIR",
        "UV_NATIVE_TLS",
        "UV_OFFLINE",
        "UV_INDEX_STRATEGY",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)
SAFE_ENV_PREFIXES = ("LC_",)

# Network settings that fresh worktrees need to install dependencies. Their values are
# URLs that may embed user:password, so credentials are stripped before passing them on;
# authenticated indexes/proxies must be configured via uv config or netrc instead.
URL_ENV_VARS = frozenset(
    {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "UV_DEFAULT_INDEX",
        "UV_INDEX_URL",
        "UV_EXTRA_INDEX_URL",
        "UV_INDEX",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
    }
)

FIXED_TEST_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_TERMINAL_PROMPT": "0",
}

_URL_USERINFO = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)


def strip_url_credentials(value: str) -> str:
    """Removes user:password@ from every URL in value."""
    return _URL_USERINFO.sub(r"\g<scheme>", value)


def build_test_env(source: Mapping[str, str]) -> dict[str, str]:
    """Copies only allowlisted variables from source; everything else (keys, tokens,
    cloud credentials) is dropped, and URLs lose any embedded credentials."""
    env = {
        key: value
        for key, value in source.items()
        if key in SAFE_ENV_VARS or key.startswith(SAFE_ENV_PREFIXES)
    }
    env.update(
        {key: strip_url_credentials(value) for key, value in source.items() if key in URL_ENV_VARS}
    )
    env.update(FIXED_TEST_ENV)
    return env


# Pass as start_new_session: the child leads its own process group (POSIX only).
USE_PROCESS_GROUP = sys.platform != "win32"


def kill_process_tree(process: asyncio.subprocess.Process) -> None:
    """Kills the process and everything it spawned. Safe to call after it exited."""
    # sys.platform (not os.name) so type checkers skip the branch for the other OS.
    if sys.platform == "win32":
        if process.returncode is None:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
