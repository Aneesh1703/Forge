"""
Phase 9A / v2.0: Coding Agent Patch Generator Engine
Owns LLM inference for multi-file code repair with unified context.
"""

import logging
import textwrap
from pathlib import Path
from typing import Any

from app.agents.candidate.models import CandidateContext
from app.agents.coder.context import MultiFileContextBuilder
from app.agents.coder.models import CodeHunk, CodePatch, SymbolAction, SymbolTarget
from app.agents.coder.prompts import CODER_SYSTEM_PROMPT
from app.agents.llm_service import LLMService
from app.agents.plan_models import FileActionType, ImplementationPlan

logger = logging.getLogger(__name__)

_ACTION_HINTS = {
    FileActionType.MODIFY: "edit in place",
    FileActionType.CREATE: "new file: use ACTION: REPLACE_FILE with the full contents",
    FileActionType.DELETE: "remove the named symbols",
}


def format_plan_for_prompt(plan: ImplementationPlan) -> str:
    """The plan as the coder sees it: goal, the only files it may change, and the steps."""
    lines = [f"Summary: {plan.summary}"]
    if plan.rationale:
        lines.append(f"Rationale: {plan.rationale}")
    lines.append("Files you may change:")
    for fa in plan.file_actions:
        symbols = f" — symbols: {', '.join(fa.target_symbols)}" if fa.target_symbols else ""
        why = f" — {fa.description}" if fa.description else ""
        hint = _ACTION_HINTS[fa.action_type]
        lines.append(f"- {fa.action_type.value} {fa.file_path} ({hint}){symbols}{why}")
    if plan.tasks:
        lines.append("Steps:")
        for task in sorted(plan.tasks, key=lambda t: t.step_number):
            lines.append(f"{task.step_number}. {task.title}: {task.description}")
    if plan.test_targets:
        lines.append(f"Tests that must pass: {', '.join(plan.test_targets)}")
    return "\n".join(lines)


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
        import os

        self.repo_root = Path(repo_root)

        if llm_service is None:
            from app.agents.llm_service import (
                AnthropicLLMService,
                DeepSeekLLMService,
                GeminiLLMService,
                OpenAILLMService,
            )
            from app.cli.config import ConfigManager

            gemini_key = (
                ConfigManager.get_key("gemini")
                or ConfigManager.get_key("google")
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("GOOGLE_API_KEY")
            )
            openai_key = ConfigManager.get_key("openai") or os.getenv("OPENAI_API_KEY")
            anthropic_key = ConfigManager.get_key("anthropic") or os.getenv("ANTHROPIC_API_KEY")
            deepseek_key = ConfigManager.get_key("deepseek") or os.getenv("DEEPSEEK_API_KEY")

            if gemini_key and not gemini_key.startswith("sk-mock"):
                llm_service = GeminiLLMService(api_key=gemini_key)
            elif openai_key and not openai_key.startswith("sk-mock"):
                llm_service = OpenAILLMService(api_key=openai_key)
            elif anthropic_key and not anthropic_key.startswith("sk-mock"):
                llm_service = AnthropicLLMService(api_key=anthropic_key)
            elif deepseek_key and not deepseek_key.startswith("sk-mock"):
                llm_service = DeepSeekLLMService(api_key=deepseek_key)

        self.llm_service = llm_service
        self.multifile_context_builder = MultiFileContextBuilder(self.repo_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_multifile_patch(
        self,
        issue_prompt: str,
        candidate_context: CandidateContext,
        attempt_number: int = 1,
        error_feedback: str = "",
        plan: ImplementationPlan | None = None,
    ) -> CodePatch:
        """Generates a multi-file CodePatch via a single unified LLM inference pass.

        Steps:
          1. Build rich multi-file context from all candidate files.
          2. Construct a single prompt that asks the LLM to identify which
             files actually need changes and produce code for each. With a plan, the
             prompt carries it and names the only files the patch may touch.
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

        if plan is not None:
            files_block = f"APPROVED PLAN:\n{format_plan_for_prompt(plan)}\n"
            scope_rule = (
                "2. Follow the approved plan. Change ONLY files listed under "
                "'Files you may change'; a patch touching any other file is rejected.\n"
            )
        else:
            candidate_file_list = "\n".join(
                f"- {cf.file_path} (score: {cf.score.total_score})"
                for cf in candidate_context.candidate_files
            )
            files_block = f"CANDIDATE FILES:\n{candidate_file_list}\n"
            scope_rule = "2. Identify ONLY the files that actually need code changes.\n"

        prompt = (
            f"ISSUE: {issue_prompt}\n\n"
            f"{files_block}"
            f"{diagnostic_block}\n"
            f"REPOSITORY CONTEXT:\n{unified_context}\n\n"
            "INSTRUCTIONS:\n"
            "1. Analyze the issue and the candidate file snippets above.\n"
            f"{scope_rule}"
            "3. For each hunk that needs a fix, output a section like:\n"
            "   ### FILE: <relative/path/to/file.py>\n"
            "   ### ACTION: MODIFY | ADD | DELETE | REPLACE_FILE\n"
            "   ### SYMBOL: <target_function_or_class_name>\n"
            "   ```python\n"
            "   <replacement code snippet>\n"
            "   ```\n"
            "4. NEVER output the entire file contents unless using REPLACE_FILE.\n"
            "5. For MODIFY or ADD, output ONLY the specific function/class definition.\n"
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
        parsed_hunks = self._parse_multifile_response(raw_response)

        all_files = list({h["file_path"] for h in parsed_hunks})
        patch = CodePatch(
            files_changed=sorted(all_files),
            explanation=(
                f"Multi-file patch for: {issue_prompt[:80]} "
                f"(Attempt {attempt_number}, {len(all_files)} files)"
            ),
            confidence=0.90,
        )

        for item in parsed_hunks:
            target = SymbolTarget(
                file_path=str(item["file_path"]),
                qualified_symbol_name=str(item["symbol_name"]),
                expected_content_hash="",
                replacement_code=str(item["code"]),
                original_snippet=str(item.get("original_snippet", "")),
                anchor_symbol=str(item.get("anchor_symbol", "")),
                anchor_position=str(item.get("anchor_position", "after")),
            )
            act_val = (
                item["action"] if isinstance(item["action"], SymbolAction) else SymbolAction.MODIFY
            )
            hunk = CodeHunk(target_symbol=target, action=act_val)
            patch.hunks.append(hunk)

        return patch

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_multifile_response(raw: str) -> list[dict[str, Any]]:
        """Parses LLM response with ### FILE:, ### ACTION:, ### SYMBOL: markers."""
        result: list[dict[str, Any]] = []
        sections = raw.split("### FILE:")

        for section in sections[1:]:  # skip preamble before first marker
            lines = section.strip().splitlines()
            if not lines:
                continue

            file_path = lines[0].strip().strip("`").strip()
            if not file_path:
                continue

            action = SymbolAction.MODIFY
            symbol_name = "auto_detected"
            anchor_symbol = ""
            anchor_position = "after"
            code_lines: list[str] = []
            snippet_lines: list[str] = []
            in_code_fence = False
            in_snippet_fence = False

            for line in lines[1:]:
                stripped = line.strip()
                if stripped.startswith("### ACTION:"):
                    raw_act = stripped.replace("### ACTION:", "").strip().upper()
                    try:
                        action = SymbolAction(raw_act)
                    except ValueError:
                        pass
                    continue
                if stripped.startswith("### SYMBOL:"):
                    symbol_name = stripped.replace("### SYMBOL:", "").strip()
                    continue
                if stripped.startswith("### ANCHOR_SYMBOL:"):
                    anchor_symbol = stripped.replace("### ANCHOR_SYMBOL:", "").strip()
                    continue
                if stripped.startswith("### ANCHOR_POSITION:"):
                    anchor_position = stripped.replace("### ANCHOR_POSITION:", "").strip().lower()
                    continue
                if stripped.startswith("### ORIGINAL_SNIPPET:"):
                    in_snippet_fence = True
                    continue

                if stripped.startswith("```") and not in_code_fence and not in_snippet_fence:
                    in_code_fence = True
                    continue
                if stripped.startswith("```") and in_code_fence:
                    in_code_fence = False
                    continue

                if in_snippet_fence:
                    if stripped.startswith("```") and snippet_lines:
                        in_snippet_fence = False
                    else:
                        if not stripped.startswith("```"):
                            snippet_lines.append(line)
                    continue

                if in_code_fence:
                    code_lines.append(line)

            if not code_lines and action != SymbolAction.DELETE:
                code_lines = [
                    ln for ln in lines[1:] if not ln.strip().startswith("###") and ln.strip()
                ]

            code = textwrap.dedent("\n".join(code_lines)).strip()
            orig_snip = textwrap.dedent("\n".join(snippet_lines)).strip()
            result.append(
                {
                    "file_path": file_path,
                    "action": action,
                    "symbol_name": symbol_name,
                    "anchor_symbol": anchor_symbol,
                    "anchor_position": anchor_position,
                    "original_snippet": orig_snip,
                    "code": code,
                }
            )

        return result
