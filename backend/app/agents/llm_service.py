"""
LLM Service Interface & Mock Provider for Agent Reasoning
"""

import json
from typing import Any, Protocol


class LLMService(Protocol):
    """Protocol interface for LLM text completion providers."""

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        """Generates text completion response given user prompt and system prompt."""
        ...


class MockLLMService:
    """Mock LLM Service for offline testing and fallback validation."""

    def __init__(self, response_override: str | None = None) -> None:
        self._response_override = response_override
        self.call_count = 0

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        self.call_count += 1
        if self._response_override:
            return self._response_override

        mock_payload: dict[str, Any] = {
            "summary": "LLM synthesized implementation plan based on AST context analysis.",
            "file_actions": [
                {
                    "action_type": "MODIFY",
                    "file_path": "app/client.py",
                    "target_symbols": ["HTTPClient"],
                    "description": "Refactor HTTPClient to improve error resilience",
                }
            ],
            "tasks": [
                {
                    "step_number": 1,
                    "title": "Update HTTPClient handler",
                    "description": "Add exception handling wrapper",
                    "target_file": "app/client.py",
                }
            ],
            "verification_commands": ["uv run pytest tests/ -s"],
        }
        return json.dumps(mock_payload)
