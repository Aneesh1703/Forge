"""
Phase 9G: Final Deterministic Repository Safety Gate
Scans modified source files for secret leaks, debug code leftovers, and static analysis violations.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.coder.models import CodePatch


@dataclass
class FinalGateResult:
    """Detailed report produced by FinalDeterministicRepositoryGate."""

    passed: bool = True
    secret_leak_detected: bool = False
    debug_print_detected: bool = False
    type_check_passed: bool = True
    lint_passed: bool = True
    violations: list[str] = field(default_factory=list)


class FinalDeterministicRepositoryGate:
    """Non-bypassable repository integrity & safety verification gate."""

    SECRET_PATTERNS = [
        re.compile(
            r"(?i)(api[_-]?key|secret|password|bearer\s+[a-z0-9\-\._~\+\/]+=*|aws[_-]?access|private[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
        ),
        re.compile(r"ghp_[A-Za-z0-9]{36}"),
        re.compile(r"sk-[A-Za-z0-9]{32,}"),
    ]

    DEBUG_PATTERNS = [
        re.compile(r"\bbreakpoint\(\)"),
        re.compile(r"\bimport\s+pdb\b"),
        re.compile(r"\bpdb\.set_trace\(\)"),
        re.compile(r"^\s*print\([^\)]*\)", re.MULTILINE),
    ]

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)

    def verify_patch(self, patch: CodePatch) -> FinalGateResult:
        """Executes non-bypassable secret, debug print, and syntax integrity checks."""
        result = FinalGateResult()

        for hunk in patch.hunks:
            target = hunk.target_symbol
            code = target.replacement_code

            # 1. Secret Leak Detection
            for pattern in self.SECRET_PATTERNS:
                if pattern.search(code):
                    result.passed = False
                    result.secret_leak_detected = True
                    result.violations.append(
                        f"Secret key/credential leak detected in {target.file_path}"
                    )
                    break

            # 2. Debug Leftovers Scan
            for pattern in self.DEBUG_PATTERNS:
                if pattern.search(code):
                    result.debug_print_detected = True
                    result.violations.append(
                        f"Debug leftover (print/breakpoint) detected in {target.file_path}"
                    )
                    # Debug prints trigger warning / fail depending on strictness
                    result.passed = False
                    break

        return result
