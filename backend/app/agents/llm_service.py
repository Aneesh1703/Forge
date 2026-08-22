"""
LLM Service Interface & Mock Provider for Agent Reasoning
"""

import json
from typing import Any, Protocol


class LLMService(Protocol):
    """Protocol interface for LLM text completion providers."""

    total_prompt_tokens: int
    total_completion_tokens: int

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        """Generates text completion response given user prompt and system prompt."""
        ...


class MockLLMService:
    """Mock LLM Service for offline testing and fallback validation."""

    def __init__(self, response_override: str | None = None) -> None:
        self._response_override = response_override
        self.call_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        self.call_count += 1
        if self._response_override:
            content = self._response_override
        else:
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
            content = json.dumps(mock_payload)

        self.total_prompt_tokens += max(10, len(prompt) // 4)
        self.total_completion_tokens += max(10, len(content) // 4)
        return content


class DeepSeekLLMService:
    """Live DeepSeek LLM Provider for real agent code generation."""

    def __init__(self, api_key: str | None = None, model: str = "deepseek-chat") -> None:
        import os

        from dotenv import load_dotenv

        load_dotenv()
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model
        self.base_url = "https://api.deepseek.com/chat/completions"
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

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

        def _make_req() -> tuple[str, int, int]:
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
                content = str(res_data["choices"][0]["message"]["content"])
                usage = res_data.get("usage", {})
                p_tok = usage.get("prompt_tokens", len(prompt) // 4)
                c_tok = usage.get("completion_tokens", len(content) // 4)
                return content, p_tok, c_tok

        content, p_tok, c_tok = await asyncio.to_thread(_make_req)
        self.total_prompt_tokens += p_tok
        self.total_completion_tokens += c_tok
        return content


class OpenAILLMService:
    """Live OpenAI LLM Provider (GPT-4o / GPT-4o-mini)."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o") -> None:
        import os

        from dotenv import load_dotenv

        load_dotenv()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = "https://api.openai.com/v1/chat/completions"
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        import asyncio
        import json
        import urllib.request

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set.")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        def _make_req() -> tuple[str, int, int]:
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
                content = str(res_data["choices"][0]["message"]["content"])
                usage = res_data.get("usage", {})
                p_tok = usage.get("prompt_tokens", len(prompt) // 4)
                c_tok = usage.get("completion_tokens", len(content) // 4)
                return content, p_tok, c_tok

        content, p_tok, c_tok = await asyncio.to_thread(_make_req)
        self.total_prompt_tokens += p_tok
        self.total_completion_tokens += c_tok
        return content


class AnthropicLLMService:
    """Live Anthropic LLM Provider (Claude 3.5 Sonnet)."""

    def __init__(
        self, api_key: str | None = None, model: str = "claude-3-5-sonnet-20241022"
    ) -> None:
        import os

        from dotenv import load_dotenv

        load_dotenv()
        self.api_key: str = (api_key or os.getenv("ANTHROPIC_API_KEY", "")) or ""
        self.model = model
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        import asyncio
        import json
        import urllib.request

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set.")

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        def _make_req() -> tuple[str, int, int]:
            req = urllib.request.Request(
                self.base_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                content = str(res_data["content"][0]["text"])
                usage = res_data.get("usage", {})
                p_tok = usage.get("input_tokens", len(prompt) // 4)
                c_tok = usage.get("output_tokens", len(content) // 4)
                return content, p_tok, c_tok

        content, p_tok, c_tok = await asyncio.to_thread(_make_req)
        self.total_prompt_tokens += p_tok
        self.total_completion_tokens += c_tok
        return content


class GeminiLLMService:
    """Live Google Gemini Provider (Gemini 1.5 Pro / Flash)."""

    def __init__(self, api_key: str | None = None, model: str = "gemini-1.5-pro") -> None:
        import os

        from dotenv import load_dotenv

        load_dotenv()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        self.model = model
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    async def generate_completion(self, prompt: str, system_prompt: str = "") -> str:
        import asyncio
        import json
        import urllib.request

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY is not set.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}],
            }

        def _make_req() -> tuple[str, int, int]:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                content = str(res_data["candidates"][0]["content"]["parts"][0]["text"])
                usage = res_data.get("usageMetadata", {})
                p_tok = usage.get("promptTokenCount", len(prompt) // 4)
                c_tok = usage.get("candidatesTokenCount", len(content) // 4)
                return content, p_tok, c_tok

        content, p_tok, c_tok = await asyncio.to_thread(_make_req)
        self.total_prompt_tokens += p_tok
        self.total_completion_tokens += c_tok
        return content
