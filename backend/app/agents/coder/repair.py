"""
Phase 9E: Auto-Fix Repair Loop Engine
Orchestrates iterative patch application, testing, and LLM repair with diagnostic feedback.
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.candidate.models import CandidateContext
from app.agents.coder.coder import CodingAgent
from app.agents.coder.diagnostics import FailureDiagnosis, TracebackParser
from app.agents.coder.models import CodePatch, ExecutionPolicy
from app.agents.coder.patch_builder import PatchBuilder
from app.agents.coder.test_generator import TestGeneratorAgent
from app.agents.coder.validator import PatchSafetyGate
from app.agents.plan_models import ImplementationPlan
from app.execution.models import TestResult
from app.execution.runner import TestExecutionEngine
from app.execution.worktree import GitWorktreeManager

PYTEST_NO_TESTS_COLLECTED = 5
MAX_FEEDBACK_OUTPUT_CHARS = 4000
MAX_FEEDBACK_TEST_CHARS = 3000
MAX_HISTORY_DETAIL_CHARS = 1000


@dataclass
class RepairState:
    """State tracking object for the auto-fix repair loop."""

    success: bool = False
    attempt: int = 1
    max_attempts: int = 3
    last_patch: CodePatch | None = None
    last_test_result: TestResult | None = None
    last_diagnosis: FailureDiagnosis | None = None
    reproducer_test_path: str | None = None
    test_targets: list[str] = field(default_factory=list)
    policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS
    summary: str = ""
    # One entry per attempt, so a job that passes on attempt 3 still shows why 1 and 2 failed.
    history: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        outcome: str,
        detail: str,
        patch: CodePatch | None = None,
        test_result: TestResult | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "attempt": self.attempt,
            "stage": "repair_loop",
            "outcome": outcome,
            "detail": detail[:MAX_HISTORY_DETAIL_CHARS],
        }
        if patch is not None:
            entry["files_changed"] = list(patch.files_changed)
        if test_result is not None:
            entry["total_tests"] = test_result.total_tests
            entry["failed_tests"] = test_result.failed_tests
        self.history.append(entry)


class AutoFixLoop:
    """Applies a patch in a fresh worktree, runs tests, and re-prompts the LLM on failure."""

    def __init__(
        self,
        repo_root: str | Path,
        coding_agent: CodingAgent | None = None,
        test_engine: TestExecutionEngine | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.coding_agent = coding_agent or CodingAgent(self.repo_root)
        self.test_engine = test_engine or TestExecutionEngine()
        self.test_generator = TestGeneratorAgent(llm_service=self.coding_agent.llm_service)
        self.worktree_manager = GitWorktreeManager(self.repo_root)
        self.safety_gate = PatchSafetyGate(self.repo_root)
        self.max_attempts = max_attempts

    async def execute_repair_loop(
        self,
        plan: ImplementationPlan,
        job_id: str | uuid.UUID,
        issue_prompt: str,
        candidate_context: CandidateContext,
        initial_patch: CodePatch,
        policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS,
    ) -> RepairState:
        """Runs up to max_attempts of apply → test → LLM repair.

        Attempt 1 tests initial_patch (already validated by the caller). Each later
        attempt asks the CodingAgent for a new patch, feeding back the previous failure.
        Every attempt gets a fresh worktree so hunks from earlier attempts never stack.
        """
        state = RepairState(max_attempts=self.max_attempts, policy=policy)
        reproducer_source: str | None = None
        patch = initial_patch
        feedback = ""

        for attempt in range(1, self.max_attempts + 1):
            state.attempt = attempt

            if attempt > 1:
                try:
                    patch = await self.coding_agent.generate_multifile_patch(
                        issue_prompt=issue_prompt,
                        candidate_context=candidate_context,
                        attempt_number=attempt,
                        error_feedback=feedback,
                        plan=plan,
                    )
                except Exception as e:
                    state.summary = f"Attempt {attempt}: patch generation failed - {e}"
                    state.record("generation_failed", str(e))
                    break

                safety_res = self.safety_gate.validate(plan, patch)
                if not safety_res.is_valid:
                    feedback = "Patch safety gate rejected the patch: " + "; ".join(
                        safety_res.errors
                    )
                    state.summary = f"Attempt {attempt}: {feedback}"
                    state.record("safety_rejected", feedback, patch)
                    continue

            with self.worktree_manager.isolated_worktree(f"{job_id}-attempt-{attempt}") as wt:
                try:
                    PatchBuilder(wt).apply_patch(patch, verify_hash=False)
                except Exception as e:
                    feedback = f"Patch could not be applied to the repository: {e}"
                    state.summary = f"Attempt {attempt}: {feedback}"
                    state.record("apply_failed", feedback, patch)
                    continue
                state.last_patch = patch

                if state.reproducer_test_path is None:
                    reproducer_source = await self._generate_reproducer(wt, issue_prompt, patch)
                    if reproducer_source:
                        state.reproducer_test_path = TestGeneratorAgent.test_path_for(issue_prompt)
                    state.test_targets = self._collect_test_targets(
                        wt, state.reproducer_test_path, plan
                    )

                if state.reproducer_test_path and reproducer_source:
                    test_file = wt / state.reproducer_test_path
                    test_file.parent.mkdir(parents=True, exist_ok=True)
                    test_file.write_text(reproducer_source, encoding="utf-8")

                test_res = await self.test_engine.run_tests(
                    worktree_path=wt, test_targets=state.test_targets or None
                )

            state.last_test_result = test_res

            if test_res.passed:
                state.success = True
                state.summary = f"Tests passed on attempt {attempt}."
                state.record("tests_passed", state.summary, patch, test_res)
                return state

            if test_res.exit_code == PYTEST_NO_TESTS_COLLECTED:
                state.summary = "No tests were collected, so the patch could not be verified."
                state.record("no_tests_collected", state.summary, patch, test_res)
                break

            diagnosis = TracebackParser.parse(test_res.traceback)
            state.last_diagnosis = diagnosis
            state.summary = f"Attempt {attempt} failed: {diagnosis.root_cause_summary}"
            state.record("tests_failed", diagnosis.root_cause_summary, patch, test_res)
            feedback = self._build_test_feedback(diagnosis, test_res, reproducer_source)

        return state

    async def _generate_reproducer(
        self, worktree: Path, issue_prompt: str, patch: CodePatch
    ) -> str | None:
        """Generates the reproducer test against the patched sources in the worktree."""
        sources: dict[str, str] = {}
        for rel_path in patch.files_changed:
            path = worktree / rel_path
            if path.is_file():
                sources[rel_path] = path.read_text(encoding="utf-8", errors="replace")
        return await self.test_generator.generate_test_source(issue_prompt, sources)

    @staticmethod
    def _collect_test_targets(
        worktree: Path, reproducer_path: str | None, plan: ImplementationPlan
    ) -> list[str]:
        """Reproducer test plus the plan's test targets that exist in the worktree."""
        targets = [reproducer_path] if reproducer_path else []
        for path in plan.test_targets:
            if path not in targets and (worktree / path).is_file():
                targets.append(path)
        return targets

    @staticmethod
    def _build_test_feedback(
        diagnosis: FailureDiagnosis, test_res: TestResult, reproducer_source: str | None
    ) -> str:
        """Formats a test failure as diagnostic feedback for the next LLM attempt."""
        parts = [
            "The previous patch was applied but the tests failed.",
            f"Root cause: {diagnosis.root_cause_summary}",
            f"Test output (tail):\n{test_res.traceback[-MAX_FEEDBACK_OUTPUT_CHARS:]}",
        ]
        if reproducer_source:
            parts.append(
                "The patch must make this test pass:\n"
                f"{reproducer_source[:MAX_FEEDBACK_TEST_CHARS]}"
            )
        return "\n\n".join(parts)
