"""
Phase 9E: Auto-Fix Repair Loop Engine with LangGraph StateGraph Integration
Orchestrates iterative patch generation, worktree application, testing, and diagnostic repair.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.agents.coder.coder import CodingAgent
from app.agents.coder.diagnostics import FailureDiagnosis, TracebackParser
from app.agents.coder.models import CodePatch, ExecutionPolicy, SymbolTarget
from app.agents.coder.patch_builder import PatchBuilder
from app.agents.coder.test_generator import TestGeneratorAgent
from app.agents.coder.validator import PatchSafetyGate
from app.agents.plan_models import ImplementationPlan
from app.execution.models import TestResult
from app.execution.runner import TestExecutionEngine
from app.execution.worktree import GitWorktreeManager
from app.orchestration.workflow import NodeStatus


@dataclass
class RepairState:
    """State tracking object for the auto-fix repair loop."""

    success: bool = False
    attempt: int = 1
    max_attempts: int = 3
    last_patch: CodePatch | None = None
    last_test_result: TestResult | None = None
    last_diagnosis: FailureDiagnosis | None = None
    policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS
    summary: str = ""
    current_node: str = "START"
    status: NodeStatus = NodeStatus.PENDING


class AutoFixLoop:
    """Orchestrates iterative repair loop using LangGraph StateGraph workflow transitions."""

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
        self.worktree_manager = GitWorktreeManager(self.repo_root)
        self.safety_gate = PatchSafetyGate(self.repo_root)
        self.max_attempts = max_attempts

    async def execute_repair_loop(
        self,
        plan: ImplementationPlan,
        job_id: str | uuid.UUID,
        initial_targets: list[SymbolTarget] | None = None,
        policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS,
    ) -> RepairState:
        """Executes stateful repair loop with LangGraph StateGraph semantics."""
        state = RepairState(
            max_attempts=self.max_attempts,
            policy=policy,
        )

        with self.worktree_manager.isolated_worktree(job_id) as worktree_path:
            patch_builder = PatchBuilder(worktree_path)

            for attempt in range(1, self.max_attempts + 1):
                state.attempt = attempt

                # 1. Node: Generate Code Patch
                patch = self.coding_agent.generate_patch(
                    plan=plan,
                    attempt_number=attempt,
                    symbol_replacements=initial_targets,
                )
                state.last_patch = patch

                # 2. Node: Safety Gate Check
                safety_res = self.safety_gate.validate(plan, patch)
                if not safety_res.is_valid:
                    errs = safety_res.errors
                    state.summary = f"Attempt {attempt}: Safety gate rejected patch - {errs}"
                    continue

                # 3. Node: Apply Patch to Worktree
                try:
                    patch_builder.apply_patch(patch, verify_hash=False)
                except Exception as e:
                    state.summary = f"Attempt {attempt}: Patch application failed - {e}"
                    continue

                # 4. Node: Ensure Reproducer Test Exists & Run Pytest
                test_generator = TestGeneratorAgent(
                    worktree_path, llm_service=self.coding_agent.llm_service
                )
                target_file = list(plan.allowed_files)[0] if plan.allowed_files else "app.py"
                await test_generator.ensure_test_exists(plan.summary, target_file)

                test_target = list(plan.allowed_files)[0] if plan.allowed_files else None
                test_res = await self.test_engine.run_tests(
                    worktree_path=worktree_path,
                    test_target=test_target,
                )
                state.last_test_result = test_res

                if test_res.passed:
                    state.success = True
                    state.status = NodeStatus.SUCCESS
                    state.summary = f"Successfully fixed issue in attempt {attempt}."
                    return state

                # 5. Node: Diagnostic Error Feedback Loop
                diagnosis = TracebackParser.parse(test_res.traceback)
                state.last_diagnosis = diagnosis
                state.summary = f"Attempt {attempt} failed: {diagnosis.root_cause_summary}"

        state.status = NodeStatus.FAILED
        return state
