"""Google Gemini provider.

Reads GEMINI_API_KEY (or GOOGLE_API_KEY). Default model 'gemini-2.0-flash-exp'.
"""

from __future__ import annotations

import os


class GeminiProvider:
    name = "Google Gemini"
    supports_tools = True
    supports_skills = False

    def __init__(self, model: str | None = None):
        try:
            import google.generativeai as genai  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Install with: pip install 'opengriffin[gemini]'") from e
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        import google.generativeai as genai

        genai.configure(api_key=key)
        self.model = model or os.environ.get("OPENGRIFFIN_MODEL", "gemini-2.0-flash-exp")
        self._client = genai.GenerativeModel(self.model)

    async def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        # Convert OpenAI-style messages → Gemini content list
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [m["content"]]})
        # Gemini SDK is sync; run in thread
        import asyncio

        resp = await asyncio.to_thread(self._client.generate_content, contents)
        text = resp.text if hasattr(resp, "text") else str(resp)
        usage = getattr(resp, "usage_metadata", None)
        return {
            "content": text,
            "input_tokens": getattr(usage, "prompt_token_count", None) if usage else None,
            "output_tokens": getattr(usage, "candidates_token_count", None) if usage else None,
        }
