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


class DeepSeekLLMService:
    """Live DeepSeek LLM Provider for real agent code generation."""

    def __init__(self, api_key: str | None = None, model: str = "deepseek-chat") -> None:
        import os

        from dotenv import load_dotenv

        load_dotenv()
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model
        self.base_url = "https://api.deepseek.com/chat/completions"

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        import asyncio
        import json
        import urllib.request

        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        def _make_req() -> str:
            req = urllib.request.Request(
                self.base_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return str(res_data["choices"][0]["message"]["content"])

        return await asyncio.to_thread(_make_req)
