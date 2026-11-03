"""

Synthesizes a reproducer pytest test for an issue so the repair loop has something real to run.
"""

import logging
import re

from app.agents.coder.prompts import TEST_GENERATOR_SYSTEM_PROMPT
from app.agents.llm_service import LLMService

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS_PER_FILE = 6000


class TestGeneratorAgent:
    """Synthesizes a pytest reproducer test for an issue via the configured LLM."""

    __test__ = False

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service

    @staticmethod
    def test_path_for(issue_description: str) -> str:
        """Returns the repo-relative path the reproducer test for this issue is written to."""
        slug = re.sub(r"\W+", "_", issue_description.lower())[:30].strip("_") or "issue"
        return f"tests/test_forge_{slug}.py"

    async def generate_test_source(
        self, issue_description: str, source_files: dict[str, str]
    ) -> str | None:
        """Asks the LLM for a pytest file exercising the issue against the given sources.

        Returns None when no LLM is configured or generation fails, so callers never
        mistake a placeholder test for real verification.
        """
        if not self.llm_service:
            return None

        sources = "\n\n".join(
            f"# FILE: {path}\n{code[:MAX_SOURCE_CHARS_PER_FILE]}"
            for path, code in source_files.items()
        )
        prompt = (
            f"Issue: {issue_description}\n\n"
            f"Source files (repo-relative paths, tests run from the repo root):\n{sources}\n\n"
            "Write a pytest test file that fails if the issue is still present and passes "
            "once it is fixed.\n"
            "Requirements:\n"
            "- Standard pytest syntax, importing the code under test by its module path\n"
            "- Focus on the behaviour described in the issue, not unrelated features\n"
            "- Executable Python code only without markdown code blocks\n"
        )
        try:
            res = await self.llm_service.generate_completion(
                prompt, system_prompt=TEST_GENERATOR_SYSTEM_PROMPT
            )
        except Exception as e:
            logger.warning(f"Reproducer test generation failed: {e}")
            return None

        clean = (res or "").strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            end_idx = -1 if lines[-1].startswith("```") else len(lines)
            clean = "\n".join(lines[1:end_idx]).strip()
        return clean or None
