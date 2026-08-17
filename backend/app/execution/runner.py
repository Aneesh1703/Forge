"""
Phase 9C: Test Execution Engine
Executes targeted test suites via async subprocess inside worktrees with timeout caps.
"""

import asyncio
import time
from pathlib import Path

from app.execution.models import ExecutionLevel, TestResult


class TestExecutionEngine:
    """Subprocess runner for targeted test execution and cascading evaluation."""

    __test__ = False

    def __init__(self, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def run_tests(
        self,
        worktree_path: str | Path,
        test_target: str | None = None,
        level: ExecutionLevel = ExecutionLevel.TARGETED_TEST,
    ) -> TestResult:
        """Executes tests asynchronously inside worktree path."""
        cwd = Path(worktree_path).resolve()

        cmd = ["uv", "run", "pytest"]
        if test_target and level in (ExecutionLevel.TARGETED_TEST, ExecutionLevel.MODULE_TEST):
            cmd.append(test_target)

        cmd.append("-v")

        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
            duration = time.time() - start_time

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0

            passed = exit_code == 0
            failed_tests = 0
            total_tests = 0
            traceback = ""

            if not passed:
                traceback = stderr or stdout

            return TestResult(
                passed=passed,
                exit_code=exit_code,
                total_tests=total_tests,
                failed_tests=failed_tests,
                traceback=traceback,
                duration=duration,
                stdout=stdout,
                stderr=stderr,
            )

        except asyncio.TimeoutError:
            duration = time.time() - start_time
            return TestResult(
                passed=False,
                exit_code=-1,
                traceback=f"Test execution timed out after {self.timeout_seconds} seconds.",
                duration=duration,
                stderr="TimeoutError: Process SIGKILL",
            )
        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                passed=False,
                exit_code=-2,
                traceback=f"Failed to launch test runner: {e}",
                duration=duration,
                stderr=str(e),
            )
