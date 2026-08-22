"""

Coordinates deterministic and LLM components on a persistent JobState.

v2.0: The orchestrator owns the full agentic workflow:
  CandidateContextResolver → MultiFileContextBuilder → CodingAgent → PatchSafetyGate → Tests
"""

import logging
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agents.llm_service import LLMService

from app.agents.candidate import CandidateContextResolver
from app.agents.coder import (
    AutoFixLoop,
    CodePatch,
    CodingAgent,
    ExecutionPolicy,
    FinalDeterministicRepositoryGate,
    FinalReviewerAgent,
    PatchSafetyGate,
)
from app.agents.coder.patch_builder import PatchBuilder
from app.agents.plan_models import FileAction, FileActionType, ImplementationPlan
from app.cli.config import ConfigManager
from app.github.auth import GitHubAuthManager
from app.github.git_service import GitService
from app.github.pr_publisher import PRPublisher, PRRequest
from app.orchestration.state import JobState, JobStatus

logger = logging.getLogger(__name__)

MAX_SELF_HEAL_ATTEMPTS = 3


class ForgeOrchestrator:
    """Non-intelligent pipeline orchestrator managing state transitions and agent coordination.

    v2.0: The CLI delegates everything to execute_job(job_id).
    This method resolves candidates, builds context, calls the LLM via CodingAgent,
    validates patches, and runs the test repair loop autonomously.
    """

    def __init__(
        self,
        repo_root: str | Path,
        state_dir: str | Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.state_dir = Path(state_dir) if state_dir else self.repo_root / ".forge_jobs"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Resolve LLM service
        llm_service = self._create_llm_service()

        # Agent & Gate Integrations
        self.candidate_resolver = CandidateContextResolver(repo_root=self.repo_root)
        self.coding_agent = CodingAgent(repo_root=self.repo_root, llm_service=llm_service)
        self.safety_gate = PatchSafetyGate(repo_root=self.repo_root)
        self.repair_loop = AutoFixLoop(
            repo_root=self.repo_root,
            coding_agent=self.coding_agent,
            max_attempts=3,
        )
        self.repo_gate = FinalDeterministicRepositoryGate(repo_root=self.repo_root)
        self.reviewer = FinalReviewerAgent()
        self.patch_builder = PatchBuilder(repo_root=self.repo_root)
        self.git_service = GitService(repo_root=self.repo_root)

    @staticmethod
    def _create_llm_service() -> "LLMService | None":
        import os

        from dotenv import load_dotenv

        load_dotenv()

        from app.agents.llm_service import (
            AnthropicLLMService,
            DeepSeekLLMService,
            GeminiLLMService,
            OpenAILLMService,
        )

        def _resolve_key(provider: str, env_name: str) -> str | None:
            key = ConfigManager.get_key(provider)
            if key and not key.startswith("sk-mock"):
                return key
            env_key = os.getenv(env_name)
            if env_key and not env_key.startswith("sk-mock"):
                return env_key
            return key  # return mock key if no real env key found

        gemini_key = _resolve_key("gemini", "GEMINI_API_KEY") or _resolve_key(
            "google", "GOOGLE_API_KEY"
        )
        if gemini_key:
            return GeminiLLMService(api_key=gemini_key)

        openai_key = _resolve_key("openai", "OPENAI_API_KEY")
        if openai_key:
            return OpenAILLMService(api_key=openai_key)

        anthropic_key = _resolve_key("anthropic", "ANTHROPIC_API_KEY")
        if anthropic_key:
            return AnthropicLLMService(api_key=anthropic_key)

        deepseek_key = _resolve_key("deepseek", "DEEPSEEK_API_KEY")
        if deepseek_key:
            return DeepSeekLLMService(api_key=deepseek_key)

        return None

    def _sync_tokens(self, state: JobState) -> None:
        """Syncs total prompt and completion tokens from LLM service to JobState."""
        if hasattr(self, "coding_agent") and self.coding_agent and self.coding_agent.llm_service:
            svc = self.coding_agent.llm_service
            p_tok = getattr(svc, "total_prompt_tokens", 0)
            c_tok = getattr(svc, "total_completion_tokens", 0)
            if p_tok > 0 or c_tok > 0:
                state.prompt_tokens = p_tok
                state.completion_tokens = c_tok

    def get_state_path(self, job_id: str) -> Path:
        """Returns the file path for a given job's state file."""
        return self.state_dir / f"job_{job_id}.json"

    def create_job(
        self,
        issue_prompt: str,
        execution_policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS,
    ) -> JobState:
        """Initializes and persists a new JobState."""
        state = JobState(
            repository_path=str(self.repo_root),
            issue_prompt=issue_prompt,
            execution_policy=execution_policy,
            status=JobStatus.PENDING,
        )
        state.save(self.get_state_path(state.job_id))
        return state

    async def execute_job(self, job_id: str) -> JobState:
        """Executes the full agentic pipeline, updating JobState at each stage.

        v2.0 flow:
          1. Resolve candidate files via CandidateContextResolver
          2. Plan (create ImplementationPlan)
          3. Gate 1 (plan approval — MANUAL policy only)
          4. CodingAgent.generate_multifile_patch (single LLM pass)
          5. PatchSafetyGate with self-healing retry loop
          6. Worktree execution & test repair loop
          7. Final review & commit
        """
        state_path = self.get_state_path(job_id)
        state = JobState.load(state_path)

        try:
            # ==============================================================
            # Stage 1: Candidate Resolution
            # ==============================================================
            state.status = JobStatus.PLANNING
            state.save(state_path)

            cand_context = self.candidate_resolver.resolve_candidates(state.issue_prompt)
            candidate_files = [cf.file_path for cf in cand_context.candidate_files]

            if not candidate_files:
                state.status = JobStatus.FAILED
                state.error_message = "No candidate files found for this issue."
                state.save(state_path)
                return state

            # ==============================================================
            # Stage 2: Planning
            # ==============================================================
            file_actions = [FileAction(FileActionType.MODIFY, f) for f in candidate_files]
            plan = ImplementationPlan.create(
                repository_id=uuid.uuid4(),
                summary=f"Resolve issue: {state.issue_prompt}",
                file_actions=file_actions,
            )
            state.implementation_plan = asdict(plan)
            state.save(state_path)

            # ==============================================================
            # Stage 3: Gate 1 — Plan Approval (MANUAL only)
            # ==============================================================
            if state.execution_policy == ExecutionPolicy.MANUAL:
                state.status = JobStatus.AWAITING_GATE_1
                state.save(state_path)
                logger.info(f"Job {job_id} paused at Gate 1 for MANUAL approval.")
                return state

            # ==============================================================
            # Stage 4: LLM Code Generation via CodingAgent (single pass)
            # ==============================================================
            state.status = JobStatus.PATCHING
            state.save(state_path)

            patch = await self.coding_agent.generate_multifile_patch(
                issue_prompt=state.issue_prompt,
                candidate_context=cand_context,
                attempt_number=1,
            )
            state.code_patch = asdict(patch)
            self._sync_tokens(state)
            state.save(state_path)

            # ==============================================================
            # Stage 5: PatchSafetyGate with Self-Healing Retry Loop
            # ==============================================================
            safety_res = self.safety_gate.validate(plan, patch)
            attempt = 1

            while not safety_res.is_valid and attempt < MAX_SELF_HEAL_ATTEMPTS:
                attempt += 1
                error_feedback = "; ".join(safety_res.errors)
                logger.warning(
                    f"Safety Gate failed (attempt {attempt - 1}): {error_feedback}. "
                    f"Re-prompting LLM with diagnostic feedback..."
                )

                patch = await self.coding_agent.generate_multifile_patch(
                    issue_prompt=state.issue_prompt,
                    candidate_context=cand_context,
                    attempt_number=attempt,
                    error_feedback=error_feedback,
                )
                state.code_patch = asdict(patch)
                self._sync_tokens(state)
                state.save(state_path)
                safety_res = self.safety_gate.validate(plan, patch)

            if not safety_res.is_valid:
                state.status = JobStatus.FAILED
                state.error_message = (
                    f"Patch Safety Gate failed after {MAX_SELF_HEAL_ATTEMPTS} attempts: "
                    f"{safety_res.errors}"
                )
                state.save(state_path)
                return state

            # ==============================================================
            # Stage 6: Isolated Worktree Execution & Test Repair Loop
            # ==============================================================
            state.status = JobStatus.TESTING
            state.save(state_path)

            symbol_targets = [h.target_symbol for h in patch.hunks]

            repair_state = await self.repair_loop.execute_repair_loop(
                plan=plan,
                job_id=state.job_id,
                initial_targets=symbol_targets,
                policy=state.execution_policy,
            )

            state.repair_attempts = repair_state.attempt

            if repair_state.last_test_result:
                state.test_results.append(
                    {
                        "passed": repair_state.last_test_result.passed,
                        "exit_code": repair_state.last_test_result.exit_code,
                        "failed_tests": repair_state.last_test_result.failed_tests,
                        "duration": repair_state.last_test_result.duration,
                    }
                )

            # ==============================================================
            # Stage 7: Final Repo Gate & Reviewer Gate 2
            # ==============================================================
            state.status = JobStatus.REVIEWING
            final_patch = repair_state.last_patch or patch
            repo_gate_res = self.repo_gate.verify_patch(final_patch)
            state.repo_gate_passed = repo_gate_res.passed

            review_res = self.reviewer.review_patch(
                plan=plan,
                patch=final_patch,
                test_result=repair_state.last_test_result,
                policy=state.execution_policy,
            )
            state.review_decision = review_res.decision.value

            if not repair_state.success or not state.repo_gate_passed:
                if state.execution_policy != ExecutionPolicy.AUTONOMOUS:
                    state.status = JobStatus.AWAITING_GATE_2
                    state.save(state_path)
                    return state

            if self.coding_agent.llm_service:
                svc = self.coding_agent.llm_service
                state.prompt_tokens = getattr(svc, "total_prompt_tokens", 0)
                state.completion_tokens = getattr(svc, "total_completion_tokens", 0)

            state.status = JobStatus.COMPLETED
            try:
                self.patch_builder.apply_patch(final_patch, verify_hash=False)
                if plan:
                    self._publish_job_pr(state=state, plan=plan, patch=final_patch)
            except Exception as apply_err:
                logger.warning(f"Could not apply patch or publish PR: {apply_err}")

            if self.coding_agent.llm_service:
                svc = self.coding_agent.llm_service
                state.prompt_tokens = getattr(svc, "total_prompt_tokens", 0)
                state.completion_tokens = getattr(svc, "total_completion_tokens", 0)

            state.save(state_path)
            return state

        except Exception as err:
            logger.exception(f"Unhandled error in job {job_id}: {err}")
            state.status = JobStatus.FAILED
            state.error_message = str(err)
            state.save(state_path)
            return state

    def _publish_job_pr(
        self,
        state: JobState,
        plan: ImplementationPlan,
        patch: CodePatch,
    ) -> str | None:
        """Creates feature branch, commits patch, pushes to remote,
        and publishes GitHub PR if authenticated."""
        try:
            # 1. Create feature branch first, then apply patch and commit
            branch_name = self.git_service.create_feature_branch(state.job_id)
            try:
                self.patch_builder.apply_patch(patch, verify_hash=False)
            except Exception as patch_err:
                logger.warning(f"Patch apply warning in _publish_job_pr: {patch_err}")

            commit_sha = self.git_service.commit_patch(plan, patch)
            state.git_branch = branch_name
            state.commit_sha = commit_sha

            # 2. Check GitHub authentication
            if not GitHubAuthManager.is_authenticated():
                logger.info("GitHub PAT or gh CLI token not found. Skipping PR creation.")
                return None

            # 3. Push to remote
            pushed = self.git_service.push_to_remote(branch_name)
            if not pushed:
                logger.error(f"Failed to push {branch_name} to remote. Skipping PR.")
                return None

            # 4. Generate PR body & publish via REST API
            owner, repo = self.git_service.get_remote_owner_repo()
            pr_body = PRPublisher.format_pr_body(plan=plan, patch=patch)

            publisher = PRPublisher()
            pr_url = publisher.publish_pr(
                PRRequest(
                    owner=owner,
                    repo=repo,
                    head_branch=branch_name,
                    base_branch="main",
                    title=f"fix: {state.issue_prompt[:60]}",
                    body=pr_body,
                )
            )
            state.pr_url = pr_url
            return pr_url
        except Exception as err:
            logger.warning(f"Failed to publish PR automatically: {err}")
            return None

    async def resume_job(
        self,
        job_id: str,
        gate_1_approved: bool | None = None,
        gate_2_approved: bool | None = None,
        gate_3_approved: bool | None = None,
        publish_pr: bool = False,
    ) -> JobState:
        """Resumes a paused or awaiting job from its stored JobState."""
        state_path = self.get_state_path(job_id)
        state = JobState.load(state_path)

        if state.status == JobStatus.AWAITING_GATE_1:
            if gate_1_approved is True:
                state.status = JobStatus.PATCHING
                state.save(state_path)
                logger.info(f"Job {job_id} Gate 1 approved. Resuming pipeline.")
                return await self.execute_job(job_id=state.job_id)
            elif gate_1_approved is False:
                state.status = JobStatus.ABORTED
                state.save(state_path)
                return state

        elif state.status in (
            JobStatus.AWAITING_GATE_2,
            JobStatus.AWAITING_GATE_3,
            JobStatus.COMPLETED,
        ):
            if gate_2_approved is True or gate_3_approved is True or publish_pr:
                state.status = JobStatus.PUBLISHING
                state.save(state_path)

                # Reconstruct plan and patch to execute publication
                if state.implementation_plan and state.code_patch:
                    plan = self._reconstruct_plan(state.implementation_plan)
                    patch = self._reconstruct_patch(state.code_patch)
                    self._publish_job_pr(state=state, plan=plan, patch=patch)

                state.status = JobStatus.COMPLETED
                state.save(state_path)
                return state
            elif gate_2_approved is False or gate_3_approved is False:
                state.status = JobStatus.ABORTED
                state.save(state_path)
                return state

        return state

    @staticmethod
    def _reconstruct_plan(
        plan_dict: dict[str, str | list[dict[str, str]]],
    ) -> ImplementationPlan:
        """Reconstructs an ImplementationPlan object from a serialized dict."""
        actions: list[FileAction] = []
        raw_actions = plan_dict.get("file_actions", [])
        if isinstance(raw_actions, list):
            for a in raw_actions:
                val_type = a.get("action_type", "MODIFY")
                raw_type = (
                    val_type.split(".")[-1]
                    if isinstance(val_type, str)
                    else str(val_type).split(".")[-1]
                )
                val_fp = a.get("file_path") or a.get("target_file") or ""
                target_fp = val_fp if isinstance(val_fp, str) else str(val_fp)
                actions.append(
                    FileAction(
                        action_type=FileActionType(raw_type),
                        file_path=target_fp,
                    )
                )

        plan_id = uuid.uuid4()
        if "plan_id" in plan_dict and isinstance(plan_dict["plan_id"], str):
            try:
                plan_id = uuid.UUID(plan_dict["plan_id"])
            except ValueError:
                pass

        repo_id = uuid.uuid4()
        if "repository_id" in plan_dict and isinstance(plan_dict["repository_id"], str):
            try:
                repo_id = uuid.UUID(plan_dict["repository_id"])
            except ValueError:
                pass

        return ImplementationPlan(
            plan_id=plan_id,
            repository_id=repo_id,
            summary=str(plan_dict.get("summary", "")),
            file_actions=actions,
        )

    @staticmethod
    def _reconstruct_patch(
        patch_dict: dict[str, Any],
    ) -> CodePatch:
        """Reconstructs a CodePatch object from a serialized dict."""
        try:
            return CodePatch.from_dict(patch_dict)
        except Exception:
            files = patch_dict.get("files_changed", [])
            files_list = [str(f) for f in files] if isinstance(files, list) else []
            return CodePatch(files_changed=files_list, hunks=[])
