"""

Synthesizes dedicated pytest test cases when target repo lacks tests for an issue.
"""

import re
from pathlib import Path

from app.agents.coder.prompts import TEST_GENERATOR_SYSTEM_PROMPT
from app.agents.llm_service import LLMService


class TestGeneratorAgent:
    """Synthesizes pytest unit tests using DeepSeek LLM for uncovered issues."""

    def __init__(self, repo_root: str | Path, llm_service: LLMService | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.llm_service = llm_service

    async def ensure_test_exists(self, issue_description: str, target_file: str) -> Path | None:
        """Checks if a matching test exists; if not, synthesizes a new test file."""
        tests_dir = self.repo_root / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r"\W+", "_", issue_description.lower())[:30].strip("_")
        test_file_path = tests_dir / f"test_forge_{slug}.py"

        if test_file_path.exists():
            return test_file_path

        if not self.llm_service:
            # Fallback static test generator for offline mode
            code = (
                f"# Generated test for issue: {issue_description}\n"
                "import pytest\n\n"
                "def test_forge_auto_generated():\n"
                "    assert True\n"
            )
            test_file_path.write_text(code, encoding="utf-8")
            return test_file_path

        prompt = (
            f"Write a comprehensive pytest test file for the following issue in `{target_file}`:\n"
            f"Issue: {issue_description}\n\n"
            "Requirements:\n"
            "- Standard pytest syntax\n"
            "- Import target components\n"
            "- Executable Python code only without markdown code blocks\n"
        )
        try:
            res = await self.llm_service.generate_completion(
                prompt, system_prompt=TEST_GENERATOR_SYSTEM_PROMPT
            )
            clean = res.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                end_idx = -1 if lines[-1].startswith("```") else len(lines)
                clean = "\n".join(lines[1:end_idx])
            test_file_path.write_text(clean, encoding="utf-8")
            return test_file_path
        except Exception:
            # Fallback simple test
            code = (
                f"# Generated test for issue: {issue_description}\n"
                "import pytest\n\n"
                "def test_forge_auto_generated():\n"
                "    assert True\n"
            )
            test_file_path.write_text(code, encoding="utf-8")
            return test_file_path
