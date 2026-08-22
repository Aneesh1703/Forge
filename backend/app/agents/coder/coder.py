"""
Phase 9A / v2.0: Coding Agent Patch Generator Engine
Owns LLM inference for multi-file code repair with unified context.
"""

import logging
import textwrap
from pathlib import Path

from app.agents.candidate.models import CandidateContext
from app.agents.coder.complexity import ComplexityScorer
from app.agents.coder.context import MinimalContextBuilder, MultiFileContextBuilder
from app.agents.coder.models import CodeHunk, CodePatch, SymbolTarget
from app.agents.coder.prompts import CODER_SYSTEM_PROMPT
from app.agents.llm_service import LLMService
from app.agents.plan_models import ImplementationPlan

logger = logging.getLogger(__name__)


class CodingAgent:
    """Generates symbol-aware code patches from ImplementationPlan and AST context.

    In v2.0 the CodingAgent owns LLM inference:
      1. Builds unified multi-file context from CandidateContext.
      2. Calls LLM once per repair attempt with full context.
      3. Cleans / dedents the response and constructs a CodePatch.
    """

    def __init__(
        self,
        repo_root: str | Path,
        llm_service: LLMService | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.llm_service = llm_service
        self.context_builder = MinimalContextBuilder(self.repo_root)
        self.multifile_context_builder = MultiFileContextBuilder(self.repo_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_patch(
        self,
        plan: ImplementationPlan,
        attempt_number: int = 1,
        symbol_replacements: list[SymbolTarget] | None = None,
    ) -> CodePatch:
        """Generates a structured CodePatch adhering to allowed_files & hash bounds."""
        complexity = ComplexityScorer.evaluate(plan, attempt_number=attempt_number)
        context_str = self.context_builder.build_context(plan, complexity)  # noqa: F841

        patch = CodePatch(
            files_changed=sorted(list(plan.allowed_files)),
            explanation=f"Generated patch for plan #{plan.plan_id} (Attempt {attempt_number})",
            confidence=0.95,
        )

        if symbol_replacements:
            for target in symbol_replacements:
                if target.file_path in plan.allowed_files:
                    hunk = CodeHunk(target_symbol=target)
                    patch.hunks.append(hunk)

        return patch

    async def generate_multifile_patch(
        self,
        issue_prompt: str,
        candidate_context: CandidateContext,
        attempt_number: int = 1,
        error_feedback: str = "",
    ) -> CodePatch:
        """Generates a multi-file CodePatch via a single unified LLM inference pass.

        Steps:
          1. Build rich multi-file context from all candidate files.
          2. Construct a single prompt that asks the LLM to identify which
             files actually need changes and produce code for each.
          3. Parse the LLM response into per-file SymbolTargets.
          4. Return a CodePatch with one hunk per changed file.
        """
        if not self.llm_service:
            raise ValueError(
                "LLM service required for multi-file patch generation. "
                "Configure DEEPSEEK_API_KEY via /config or .env"
            )

        # 1. Build unified context
        unified_context = self.multifile_context_builder.build_multifile_context(candidate_context)

        # 2. Build prompt
        diagnostic_block = ""
        if error_feedback:
            diagnostic_block = (
                "\nDIAGNOSTIC ERROR FROM PREVIOUS ATTEMPT:\n"
                f"{error_feedback}\n"
                "Fix the errors listed above.\n"
            )

        candidate_file_list = "\n".join(
            f"- {cf.file_path} (score: {cf.score.total_score})"
            for cf in candidate_context.candidate_files
        )

        prompt = (
            f"ISSUE: {issue_prompt}\n\n"
            f"CANDIDATE FILES:\n{candidate_file_list}\n"
            f"{diagnostic_block}\n"
            f"REPOSITORY CONTEXT:\n{unified_context}\n\n"
            "INSTRUCTIONS:\n"
            "1. Analyze the issue and the candidate file snippets above.\n"
            "2. Identify ONLY the files that actually need code changes.\n"
            "3. For each file that needs a fix, output a section like:\n"
            "   ### FILE: <relative/path/to/file.py>\n"
            "   ```python\n"
            "   <replacement code snippet>\n"
            "   ```\n"
            "4. Output ONLY the changed function/class bodies (under 50 lines each).\n"
            "5. Do NOT output files that do not need changes.\n"
            "6. Do NOT wrap code in def fix_...() monkey-patch wrappers.\n"
            "7. Code must start at column 0 with no leading indentation.\n"
            f"(Attempt #{attempt_number})"
        )

        # 3. Call LLM
        raw_response = await self.llm_service.generate_completion(
            prompt, system_prompt=CODER_SYSTEM_PROMPT
        )

        if not raw_response or not isinstance(raw_response, str):
            raise ValueError("Empty LLM response during multi-file patch generation.")

        # 4. Parse response into per-file targets
        file_patches = self._parse_multifile_response(raw_response)

        all_files = list(file_patches.keys())
        patch = CodePatch(
            files_changed=sorted(all_files),
            explanation=(
                f"Multi-file patch for: {issue_prompt[:80]} "
                f"(Attempt {attempt_number}, {len(all_files)} files)"
            ),
            confidence=0.90,
        )

        for file_path, code in file_patches.items():
            target = SymbolTarget(
                file_path=file_path,
                qualified_symbol_name="auto_detected",
                expected_content_hash="",
                replacement_code=code,
            )
            patch.hunks.append(CodeHunk(target_symbol=target))

        return patch

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_multifile_response(raw: str) -> dict[str, str]:
        """Parses LLM response with ### FILE: markers into a dict of {path: code}."""
        result: dict[str, str] = {}
        sections = raw.split("### FILE:")

        for section in sections[1:]:  # skip preamble before first marker
            lines = section.strip().splitlines()
            if not lines:
                continue

            file_path = lines[0].strip().strip("`").strip()
            if not file_path:
                continue

            # Extract code between ``` fences
            code_lines: list[str] = []
            in_fence = False
            for line in lines[1:]:
                stripped = line.strip()
                if stripped.startswith("```") and not in_fence:
                    in_fence = True
                    continue
                if stripped.startswith("```") and in_fence:
                    in_fence = False
                    continue
                if in_fence:
                    code_lines.append(line)

            # If no fences found, take all non-empty lines after the path
            if not code_lines:
                code_lines = [ln for ln in lines[1:] if ln.strip()]

            code = textwrap.dedent("\n".join(code_lines)).strip()
            if code:
                result[file_path] = code

        return result
