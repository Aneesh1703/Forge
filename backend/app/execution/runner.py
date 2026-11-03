"""
Phase 9C: Test Execution Engine
Executes targeted test suites via async subprocess inside worktrees with timeout caps.
"""

import asyncio
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path

from app.execution.isolation import USE_PROCESS_GROUP, build_test_env, kill_process_tree
from app.execution.models import ExecutionLevel, TestResult

PYTEST_COUNT_PATTERN = re.compile(r"(\d+) (passed|failed|error|errors)\b")
MAX_TRACEBACK_CHARS = 8000
# After the test process exits and its group is killed, pipes should close at once; this
# only bounds the wait when something outside the group still holds them (e.g. Windows).
PIPE_DRAIN_SECONDS = 5.0
EXIT_POLL_SECONDS = 0.05


async def _wait_for_exit(process: asyncio.subprocess.Process, timeout: float) -> bool:
    """Waits for the process itself to exit; True if it did within timeout.

    process.wait() is not used because asyncio also waits for every pipe to close, which
    a background child that inherited stdout would delay until the timeout.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while process.returncode is None:
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(EXIT_POLL_SECONDS)
    return True


async def _drain(stream: asyncio.StreamReader | None, sink: bytearray) -> None:
    """Reads a pipe into sink chunk by chunk, so output survives a cancelled read."""
    if stream is None:
        return
    while chunk := await stream.read(65536):
        sink.extend(chunk)


class TestExecutionEngine:
    """Subprocess runner for targeted test execution and cascading evaluation."""

    __test__ = False

    def __init__(
        self,
        timeout_seconds: float = 60.0,
        base_command: list[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.base_command = base_command or ["uv", "run", "pytest"]
        # Fixed environment for tests; defaults to an allowlisted copy of os.environ
        # taken at run time, so Forge's own secrets never reach LLM-written test code.
        self._env = env

    async def run_tests(
        self,
        worktree_path: str | Path,
        test_targets: list[str] | None = None,
        level: ExecutionLevel = ExecutionLevel.TARGETED_TEST,
    ) -> TestResult:
        """Executes tests asynchronously inside worktree path."""
        cwd = Path(worktree_path).resolve()

        cmd = list(self.base_command)
        if test_targets and level in (ExecutionLevel.TARGETED_TEST, ExecutionLevel.MODULE_TEST):
            cmd.extend(test_targets)
        cmd.append("-v")

        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=dict(self._env) if self._env is not None else build_test_env(os.environ),
                start_new_session=USE_PROCESS_GROUP,
            )
        except Exception as e:
            return TestResult(
                passed=False,
                exit_code=-2,
                traceback=f"Failed to launch test runner: {e}",
                duration=time.time() - start_time,
                stderr=str(e),
            )

        stdout_buf, stderr_buf = bytearray(), bytearray()
        readers = asyncio.gather(
            _drain(process.stdout, stdout_buf), _drain(process.stderr, stderr_buf)
        )
        timed_out = False
        try:
            timed_out = not await _wait_for_exit(process, self.timeout_seconds)
        finally:
            # Kill the whole group: hung tests on timeout, leftover servers/workers
            # otherwise. Also runs on cancellation, so nothing outlives the job.
            kill_process_tree(process)
            try:
                await asyncio.wait_for(readers, timeout=PIPE_DRAIN_SECONDS)
            except asyncio.TimeoutError:
                pass  # wait_for cancelled the readers; keep the output drained so far

        duration = time.time() - start_time
        stdout = stdout_buf.decode("utf-8", errors="replace")
        stderr = stderr_buf.decode("utf-8", errors="replace")

        if timed_out:
            return TestResult(
                passed=False,
                exit_code=-1,
                traceback=f"Test execution timed out after {self.timeout_seconds} seconds.",
                duration=duration,
                stdout=stdout,
                stderr="TimeoutError: Process SIGKILL",
            )

        exit_code = process.returncode if process.returncode is not None else -1
        passed = exit_code == 0
        counts = {"passed": 0, "failed": 0}
        for num, kind in PYTEST_COUNT_PATTERN.findall(stdout):
            counts["passed" if kind == "passed" else "failed"] += int(num)

        # pytest reports failures on stdout; stderr mostly carries uv/env noise.
        traceback = "" if passed else (stdout + "\n" + stderr).strip()[-MAX_TRACEBACK_CHARS:]
        return TestResult(
            passed=passed,
            exit_code=exit_code,
            total_tests=counts["passed"] + counts["failed"],
            failed_tests=counts["failed"],
            traceback=traceback,
            duration=duration,
            stdout=stdout,
            stderr=stderr,
        )
