"""Cohere provider — uses the official cohere SDK (not OpenAI-compatible)."""

from __future__ import annotations

import os


class CohereProvider:
    name = "Cohere"
    supports_tools = True
    supports_skills = False

    def __init__(self, model: str | None = None):
        try:
            import cohere  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Install with: pip install 'opengriffin[cohere]'") from e
        key = os.environ.get("COHERE_API_KEY")
        if not key:
            raise RuntimeError("COHERE_API_KEY not set")
        import cohere

        self._client = cohere.AsyncClientV2(api_key=key)
        self.model = model or os.environ.get("OPENGRIFFIN_MODEL", "command-r-plus-08-2024")

    async def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        resp = await self._client.chat(model=self.model, messages=messages)
        return {
            "content": resp.message.content[0].text if resp.message.content else "",
            "input_tokens": getattr(resp.usage, "input_tokens", None) if resp.usage else None,
            "output_tokens": getattr(resp.usage, "output_tokens", None) if resp.usage else None,
        }
