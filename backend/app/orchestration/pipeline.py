"""

Coordinates deterministic and LLM components on a persistent JobState.

The orchestrator owns the full workflow, persisting JobState after every stage:
  UNDERSTAND → INVESTIGATE → PLAN → GATE_1 → CODE → TEST/GATES → PUBLISH
The approved plan is a contract: it bounds the coder's context and the files a patch may
touch, chooses the tests that run, and drives the PR description.
"""

import json
import logging
import uuid
from collections.abc import Callable
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
from app.agents.coder.context import plan_context
from app.agents.coder.patch_builder import PatchApplicationError, PatchBuilder
from app.agents.evidence import EvidenceInvestigator
from app.agents.evidence.investigator import tests_for
from app.agents.issue_understander import IssueUnderstander, ground, split_issue_prompt
from app.agents.plan_models import FileActionType, ImplementationPlan
from app.agents.planner import PlanningAgent
from app.cli.config import ConfigManager
from app.github.auth import GitHubAuthManager
from app.github.git_remote import redact_credentials
from app.github.git_service import GitError, GitService
from app.github.pr_publisher import PRPublisher, PRRequest
from app.orchestration.publish_policy import decide_publish
from app.orchestration.state import JobState, JobStatus
from app.repository.listing import is_test_path, list_repo_files

logger = logging.getLogger(__name__)

MAX_SELF_HEAL_ATTEMPTS = 3


def with_mapped_tests(plan: ImplementationPlan, repo_files: frozenset[str]) -> list[str]:
    """The plan's test targets, plus planned test files and the tests named after each
    planned source file (`test_x.py` / `x_test.py`), so Gate 1 shows every test that runs."""
    tests = sorted(p for p in repo_files if is_test_path(p))
    extra: list[str] = []
    for fa in plan.file_actions:
        if fa.action_type == FileActionType.DELETE:
            continue
        if is_test_path(fa.file_path):
            extra.append(fa.file_path)
        else:
            extra += tests_for(fa.file_path, tests)
    return list(dict.fromkeys(plan.test_targets + extra))


class ForgeOrchestrator:
    """Non-intelligent pipeline orchestrator managing state transitions and agent coordination.

    The CLI delegates everything to execute_job(job_id), which understands the issue,
    investigates evidence, plans, pauses at Gate 1 when required, then codes, tests,
    reviews and publishes within the approved plan.
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

        # Stable per repository, so Repository Brain recall matches across jobs.
        self.repository_id = uuid.uuid5(uuid.NAMESPACE_URL, self.repo_root.as_uri())

        # Agent & Gate Integrations
        self.understander = IssueUnderstander()
        self.investigator = EvidenceInvestigator()
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

    def get_artifact_dir(self, job_id: str) -> Path:
        """Directory holding a job's human-readable artifacts (plan.json, plan.md)."""
        return self.state_dir / job_id

    def write_plan_artifacts(self, state: JobState) -> Path | None:
        """Exports the job's plan as plan.json and plan.md; returns the plan.md path.

        These are views for humans and tools. JobState stays the source of truth, so
        editing plan.json does not change what runs.
        """
        if not state.implementation_plan:
            return None
        plan = ImplementationPlan.from_dict(state.implementation_plan)
        out_dir = self.get_artifact_dir(state.job_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "job_id": state.job_id,
            "issue": state.issue_prompt,
            "approved": state.gate_1_approved,
            "plan": state.implementation_plan,
            "understanding": state.issue_understanding,
            "evidence": state.evidence_graph,
        }
        (out_dir / "plan.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        md_path = out_dir / "plan.md"
        md_path.write_text(plan.to_markdown(), encoding="utf-8")
        return md_path

    async def _plan_job(self, state: JobState, state_path: Path) -> ImplementationPlan:
        """UNDERSTAND → INVESTIGATE → PLAN, saving each result before the next stage."""
        state.status = JobStatus.ANALYZING
        state.save(state_path)

        repo_files = list_repo_files(self.repo_root)
        title, description = split_issue_prompt(state.issue_prompt)
        understanding = ground(self.understander.analyze_issue(title, description), repo_files)
        state.issue_understanding = understanding.to_dict()
        state.save(state_path)

        cand_context = self.candidate_resolver.resolve_candidates(state.issue_prompt)
        graph = await self.investigator.investigate(
            understanding,
            self.repository_id,
            repo_files=repo_files,
            candidate_files=[cf.file_path for cf in cand_context.candidate_files],
        )
        state.evidence_graph = graph.to_dict()
        state.status = JobStatus.PLANNING
        state.save(state_path)

        planner = PlanningAgent(self.coding_agent.llm_service, repo_files)
        plan = await planner.synthesize_plan(understanding, graph)
        plan.test_targets = with_mapped_tests(plan, repo_files)

        state.implementation_plan = plan.to_dict()
        self._sync_tokens(state)
        state.save(state_path)
        self.write_plan_artifacts(state)
        return plan

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

    async def execute_job(self, job_id: str, plan_only: bool = False) -> JobState:
        """Executes the full agentic pipeline, updating JobState at each stage.

        Flow:
          1-3. Understand the issue, investigate evidence, plan (saved as plan.json/.md)
          4. Gate 1 (plan approval — MANUAL policy, or plan_only for a preview)
          5. CodingAgent.generate_multifile_patch within the plan
          6. PatchSafetyGate with self-healing retry loop
          7. Worktree execution & test repair loop on the plan's test targets
          8. Final review & commit
        """
        state_path = self.get_state_path(job_id)
        state = JobState.load(state_path)

        try:
            # ==============================================================
            # Stages 1-3: Understand → Investigate → Plan. An approved plan is the
            # source of truth and is never rebuilt, so what the human approved is
            # what gets executed.
            # ==============================================================
            if state.gate_1_approved and state.implementation_plan:
                plan = ImplementationPlan.from_dict(state.implementation_plan)
            else:
                plan = await self._plan_job(state, state_path)
                if not plan.file_actions:
                    state.status = JobStatus.FAILED
                    state.error_message = " ".join(
                        ["The planner found no files to change; see plan.md for why."]
                        + plan.warnings
                    )
                    state.save(state_path)
                    return state

            # ==============================================================
            # Stage 4: Gate 1 — Plan Approval (MANUAL or preview, until approved)
            # ==============================================================
            needs_gate_1 = plan_only or state.execution_policy == ExecutionPolicy.MANUAL
            if needs_gate_1 and not state.gate_1_approved:
                state.status = JobStatus.AWAITING_GATE_1
                state.save(state_path)
                logger.info(f"Job {job_id} paused at Gate 1 for plan approval.")
                return state

            # ==============================================================
            # Stage 5: LLM Code Generation via CodingAgent, within the plan
            # ==============================================================
            state.status = JobStatus.PATCHING
            state.save(state_path)

            cand_context = plan_context(plan, self.repo_root, state.issue_prompt)
            patch = await self.coding_agent.generate_multifile_patch(
                issue_prompt=state.issue_prompt,
                candidate_context=cand_context,
                attempt_number=1,
                plan=plan,
            )
            state.code_patch = asdict(patch)
            self._sync_tokens(state)
            state.save(state_path)

            # ==============================================================
            # Stage 6: PatchSafetyGate with Self-Healing Retry Loop
            # ==============================================================
            safety_res = self.safety_gate.validate(plan, patch)
            attempt = 1

            while not safety_res.is_valid and attempt < MAX_SELF_HEAL_ATTEMPTS:
                attempt += 1
                error_feedback = "; ".join(safety_res.errors)
                state.repair_history.append(
                    {
                        "attempt": attempt - 1,
                        "stage": "safety_gate",
                        "outcome": "safety_rejected",
                        "detail": error_feedback[:1000],
                        "files_changed": list(patch.files_changed),
                    }
                )
                logger.warning(
                    f"Safety Gate failed (attempt {attempt - 1}): {error_feedback}. "
                    f"Re-prompting LLM with diagnostic feedback..."
                )

                patch = await self.coding_agent.generate_multifile_patch(
                    issue_prompt=state.issue_prompt,
                    candidate_context=cand_context,
                    attempt_number=attempt,
                    error_feedback=error_feedback,
                    plan=plan,
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
            # Stage 7: Isolated Worktree Execution & Test Repair Loop
            # ==============================================================
            state.status = JobStatus.TESTING
            state.save(state_path)

            repair_state = await self.repair_loop.execute_repair_loop(
                plan=plan,
                job_id=state.job_id,
                issue_prompt=state.issue_prompt,
                candidate_context=cand_context,
                initial_patch=patch,
                policy=state.execution_policy,
            )

            state.repair_attempts = repair_state.attempt
            state.repair_summary = repair_state.summary
            state.repair_history.extend(repair_state.history)
            final_patch = repair_state.last_patch or patch
            state.code_patch = asdict(final_patch)
            self._sync_tokens(state)

            if repair_state.last_test_result:
                state.test_results.append(
                    {
                        "passed": repair_state.last_test_result.passed,
                        "exit_code": repair_state.last_test_result.exit_code,
                        "total_tests": repair_state.last_test_result.total_tests,
                        "failed_tests": repair_state.last_test_result.failed_tests,
                        "duration": repair_state.last_test_result.duration,
                        "test_targets": repair_state.test_targets,
                    }
                )
            state.save(state_path)

            # ==============================================================
            # Stage 8: Final Repo Gate & Reviewer Gate 2
            # ==============================================================
            state.status = JobStatus.REVIEWING
            repo_gate_res = self.repo_gate.verify_patch(final_patch)
            state.repo_gate_passed = repo_gate_res.passed

            review_res = self.reviewer.review_patch(
                plan=plan,
                patch=final_patch,
                test_result=repair_state.last_test_result,
                policy=state.execution_policy,
            )
            state.review_decision = review_res.decision.value

            decision = decide_publish(
                tests_passed=repair_state.success,
                repo_gate_passed=repo_gate_res.passed,
                review=review_res,
            )
            state.gate_2_reasons = decision.reasons
            if not decision.auto_publish:
                state.status = JobStatus.AWAITING_GATE_2
                state.save(state_path)
                return state

            # _publish_job_pr is the only place the patch touches the real working tree.
            self._publish_job_pr(state=state, plan=plan, patch=final_patch)
            if state.commit_sha:
                state.status = JobStatus.COMPLETED
            else:
                # Tested patch could not be committed (e.g. local edits in its files):
                # hold it at Gate 2 so the user can resolve the cause and approve.
                state.status = JobStatus.AWAITING_GATE_2
                state.gate_2_reasons.append(state.error_message or "Commit failed.")
            self._sync_tokens(state)
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
        push: bool = True,
    ) -> str | None:
        """Commits the patch on a feature branch and, when push is True, pushes it and
        opens a PR (if GitHub auth is available).

        Idempotent: the patch is applied and committed only once per job, so a later
        publish only pushes and opens the PR.
        """
        if state.pr_url:
            return state.pr_url

        if not (state.commit_sha and state.git_branch):
            try:
                self._commit_on_feature_branch(state, plan, patch)
            except (GitError, PatchApplicationError) as err:
                state.error_message = f"Could not commit patch: {err}"
                logger.error(state.error_message)
                return None

        return self._open_pull_request(state, plan, patch) if push else None

    def _commit_on_feature_branch(
        self, state: JobState, plan: ImplementationPlan, patch: CodePatch
    ) -> None:
        """Applies and commits the patch on a fresh feature branch.

        Refuses to touch files with local changes. On any failure the patch files are
        restored, the original branch is checked out again, and the error is re-raised.
        """
        dirty = self.git_service.dirty_paths(patch.files_changed)
        if dirty:
            raise GitError(
                f"Patch files have uncommitted local changes: {dirty}. Commit or stash them."
            )

        original_branch = self.git_service.current_branch()
        original_ref = original_branch or self.git_service.current_ref()
        branch_name = self.git_service.create_feature_branch(state.job_id)
        try:
            self.patch_builder.apply_patch(patch, verify_hash=False)
            commit_sha = self.git_service.commit_patch(plan, patch)
        except Exception:
            self._rollback_feature_branch(patch, original_ref, branch_name)
            raise

        state.git_branch = branch_name
        state.commit_sha = commit_sha
        state.base_branch = original_branch or self.git_service.default_base_branch()

        # Return the user to where they were, so the next job branches from the same
        # base instead of stacking on this job's commit.
        try:
            self.git_service.checkout(original_ref)
        except GitError as e:
            logger.warning(
                f"Committed on {branch_name} but could not return to {original_ref}: {e}"
            )

    def _rollback_feature_branch(
        self, patch: CodePatch, original_ref: str, branch_name: str
    ) -> None:
        """Best-effort undo of a failed commit; step failures are logged, not raised,
        so the original error is what surfaces."""
        steps: list[Callable[[], None]] = [
            lambda: self.git_service.discard_paths(patch.files_changed),
            lambda: self.git_service.checkout(original_ref),
            lambda: self.git_service.delete_branch(branch_name),
        ]
        for step in steps:
            try:
                step()
            except Exception as e:
                logger.error(f"Rollback step failed: {e}")

    def _open_pull_request(
        self, state: JobState, plan: ImplementationPlan, patch: CodePatch
    ) -> str | None:
        """Pushes the committed branch and opens a PR when GitHub auth is available.

        Failures are recorded on state.error_message; the local commit stays valid.
        """
        branch_name = state.git_branch
        if not branch_name:
            return None
        if not GitHubAuthManager.is_authenticated():
            logger.info("GitHub PAT or gh CLI token not found. Skipping PR creation.")
            return None

        try:
            self.git_service.push_to_remote(branch_name)

            owner, repo = self.git_service.get_remote_owner_repo()
            pr_body = PRPublisher.format_pr_body(
                plan=plan,
                patch=patch,
                test_run=state.test_results[-1] if state.test_results else None,
            )

            publisher = PRPublisher()
            pr_url = publisher.publish_pr(
                PRRequest(
                    owner=owner,
                    repo=repo,
                    head_branch=branch_name,
                    base_branch=state.base_branch or self.git_service.default_base_branch(),
                    title=f"fix: {state.issue_prompt[:60]}",
                    body=pr_body,
                )
            )
            state.pr_url = pr_url
            return pr_url
        except Exception as err:
            state.error_message = redact_credentials(
                f"Committed locally as {state.commit_sha}, but publishing failed: {err}"
            )
            logger.error(state.error_message)
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
                # Persisted so execute_job skips the Gate 1 pause on this run.
                state.gate_1_approved = True
                state.status = JobStatus.PATCHING
                state.save(state_path)
                self.write_plan_artifacts(state)
                logger.info(f"Job {job_id} Gate 1 approved. Resuming pipeline.")
                return await self.execute_job(job_id=state.job_id)
            elif gate_1_approved is False:
                state.status = JobStatus.ABORTED
                state.save(state_path)
                return state

        # Gate 2 holds work that failed a check or needs a human; only an explicit Gate 2
        # approval (commit locally) or an explicit publish (commit + push + PR) releases
        # it. PUBLISHING means an interrupted publish, safe to retry (idempotent).
        elif state.status in (JobStatus.AWAITING_GATE_2, JobStatus.PUBLISHING):
            if publish_pr or gate_2_approved is True:
                return self._resume_publish(state, state_path, push=publish_pr)
            if gate_2_approved is False:
                state.status = JobStatus.ABORTED
                state.save(state_path)

        elif state.status == JobStatus.AWAITING_GATE_3:
            if publish_pr or gate_3_approved is True:
                return self._resume_publish(state, state_path, push=publish_pr)
            if gate_3_approved is False:
                state.status = JobStatus.ABORTED
                state.save(state_path)

        # Already committed: publishing only pushes and opens the PR. Rejecting a
        # completed job is a no-op — its commit exists.
        elif state.status == JobStatus.COMPLETED and publish_pr:
            return self._resume_publish(state, state_path, push=True)

        return state

    def _resume_publish(self, state: JobState, state_path: Path, push: bool) -> JobState:
        """Commits (if needed) and optionally pushes a resumed job.

        Never leaves it in PUBLISHING: if no commit could be made (e.g. local changes in
        the patch files), the job returns to its gate with the error so the user can fix
        the cause and approve again.
        """
        gate_status = (
            state.status
            if state.status in (JobStatus.AWAITING_GATE_2, JobStatus.AWAITING_GATE_3)
            else JobStatus.AWAITING_GATE_2
        )
        state.status = JobStatus.PUBLISHING
        state.error_message = None  # stale errors from an earlier attempt
        state.save(state_path)
        try:
            if state.implementation_plan and state.code_patch:
                plan = ImplementationPlan.from_dict(state.implementation_plan)
                patch = self._reconstruct_patch(state.code_patch)
                self._publish_job_pr(state=state, plan=plan, patch=patch, push=push)
        except Exception as err:
            logger.exception(f"Publishing job {state.job_id} failed: {err}")
            state.error_message = redact_credentials(str(err))
        state.status = JobStatus.COMPLETED if state.commit_sha else gate_status
        state.save(state_path)
        return state

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
