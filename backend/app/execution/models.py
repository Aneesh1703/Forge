"""
Phase 9C: Test Execution Engine Domain Models
"""

from dataclasses import dataclass
from enum import Enum


class ExecutionLevel(str, Enum):
    """Cascading test execution level."""

    TARGETED_TEST = "TARGETED_TEST"
    MODULE_TEST = "MODULE_TEST"
    FULL_SUITE = "FULL_SUITE"


@dataclass
class TestResult:
    """Structured test execution result."""

    __test__ = False

    passed: bool
    exit_code: int
    total_tests: int = 0
    failed_tests: int = 0
    traceback: str = ""
    duration: float = 0.0
    stdout: str = ""
    stderr: str = ""
