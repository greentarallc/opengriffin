"""Ollama provider — local models, no API key, no tool use."""

from __future__ import annotations

import os


class OllamaProvider:
    name = "Ollama (local)"
    supports_tools = False
    supports_skills = False

    def __init__(self, model: str | None = None):
        try:
            import ollama  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Install with: pip install 'opengriffin[ollama]'") from e
        self._host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1")

    async def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        import ollama

        client = ollama.AsyncClient(host=self._host)
        resp = await client.chat(model=self.model, messages=messages)
        return {"content": resp["message"]["content"]}
