"""AI provider abstraction. Bring your own key for any platform.

20+ supported providers. Configured via OPENGRIFFIN_PROVIDER + OPENGRIFFIN_MODEL,
overridable per chat by users via the /model command.

Native (full-feature) providers:
  - claude     : Claude Agent SDK (Claude Max OAuth or Anthropic key) — best DX, skills, MCP, hooks
  - anthropic  : Anthropic API direct
  - gemini     : Google Gemini
  - cohere     : Cohere Command-R
  - bedrock    : AWS Bedrock (Claude / Llama / Mistral via AWS)
  - ollama     : Local Ollama (no key, no tool use)

OpenAI-compatible flavors (all use the openai SDK with different base_urls):
  - openai     : OpenAI (GPT-4o, o1, etc.)
  - openrouter : OpenRouter passthrough to 100+ models
  - azure      : Azure OpenAI
  - deepseek   : DeepSeek (chat, reasoner)
  - xai        : Grok
  - mistral    : Mistral hosted
  - perplexity : Sonar online models
  - together   : Together AI
  - groq       : Groq fast inference
  - fireworks  : Fireworks AI
  - cerebras   : Cerebras inference
  - nvidia     : NVIDIA NIM
  - huggingface: HuggingFace Inference
  - lambda     : Lambda Labs
  - novita     : Novita AI
  - custom     : BYO endpoint (set CUSTOM_BASE_URL + CUSTOM_API_KEY)
"""

from __future__ import annotations

import os
from typing import Protocol


class ChatProvider(Protocol):
    name: str
    supports_tools: bool
    supports_skills: bool

    async def chat(self, messages: list[dict], tools: list | None = None) -> dict: ...


# OpenAI-compatible flavors are looked up dynamically via openai_compatible.FLAVORS.
NATIVE_PROVIDERS = {"claude", "anthropic", "gemini", "cohere", "bedrock", "ollama"}


def list_providers() -> dict[str, dict]:
    """Return the full catalog: provider name → {label, models, key_env}."""
    from .openai_compatible import FLAVORS as OAI_FLAVORS

    catalog: dict[str, dict] = {
        "claude": {
            "label": "Claude (Agent SDK)",
            "models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
            "key_env": "ANTHROPIC_API_KEY (or Claude Max OAuth)",
        },
        "anthropic": {
            "label": "Anthropic API",
            "models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
            "key_env": "ANTHROPIC_API_KEY",
        },
        "gemini": {
            "label": "Google Gemini",
            "models": ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"],
            "key_env": "GEMINI_API_KEY",
        },
        "cohere": {
            "label": "Cohere",
            "models": ["command-r-plus-08-2024", "command-r-08-2024"],
            "key_env": "COHERE_API_KEY",
        },
        "bedrock": {
            "label": "AWS Bedrock",
            "models": ["us.anthropic.claude-opus-4-7-v1:0", "meta.llama3-1-405b-instruct-v1:0"],
            "key_env": "AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY",
        },
        "ollama": {
            "label": "Ollama (local)",
            "models": ["llama3.1", "mistral", "qwen2.5", "deepseek-r1"],
            "key_env": "(none — local)",
        },
    }
    for flavor, cfg in OAI_FLAVORS.items():
        catalog[flavor] = {
            "label": cfg.label,
            "models": cfg.models,
            "key_env": cfg.key_env,
        }
    return catalog


def get_provider(name: str | None = None, model: str | None = None) -> ChatProvider:
    """Resolve a provider, importing only what's needed.

    `name`  : provider key (e.g. "openai"). Defaults to OPENGRIFFIN_PROVIDER env (or "claude").
    `model` : optional model id. Defaults to OPENGRIFFIN_MODEL env or provider default.
    """
    if name is None:
        name = (os.environ.get("OPENGRIFFIN_PROVIDER") or "claude").strip().lower()
    name = name.lower()
    if model:
        os.environ["OPENGRIFFIN_MODEL"] = model

    if name == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider()
    if name == "anthropic":
        from .anthropic_api import AnthropicAPIProvider

        return AnthropicAPIProvider()
    if name == "gemini":
        from .gemini import GeminiProvider

        return GeminiProvider()
    if name == "cohere":
        from .cohere import CohereProvider

        return CohereProvider()
    if name == "bedrock":
        from .bedrock import BedrockProvider

        return BedrockProvider()
    if name == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider()

    # Everything else is OpenAI-compatible
    from .openai_compatible import FLAVORS, OpenAICompatibleProvider

    if name in FLAVORS:
        return OpenAICompatibleProvider(flavor=name)

    raise ValueError(
        f"Unknown OPENGRIFFIN_PROVIDER: {name}. Try: {', '.join(sorted(list_providers().keys()))}"
    )


__all__ = ["ChatProvider", "get_provider", "list_providers", "NATIVE_PROVIDERS"]
