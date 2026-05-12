"""OpenAI-compatible providers.

Most modern AI APIs speak OpenAI's protocol. We just point an `AsyncOpenAI`
client at the right `base_url` and key. Add a row to FLAVORS to support a
new provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class FlavorConfig:
    label: str
    key_env: str  # e.g. "OPENAI_API_KEY"
    base_url: str | None  # None = OpenAI's default
    default_model: str
    models: list[str]


FLAVORS: dict[str, FlavorConfig] = {
    "openai": FlavorConfig(
        label="OpenAI",
        key_env="OPENAI_API_KEY",
        base_url=None,
        default_model="gpt-4o",
        models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini"],
    ),
    "openrouter": FlavorConfig(
        label="OpenRouter",
        key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-opus-4",
        models=[
            "anthropic/claude-opus-4",
            "openai/gpt-4o",
            "google/gemini-pro-1.5",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.1-405b-instruct",
            "x-ai/grok-2",
        ],
    ),
    "azure": FlavorConfig(
        label="Azure OpenAI",
        key_env="AZURE_OPENAI_API_KEY",
        base_url=None,  # set via AZURE_OPENAI_ENDPOINT
        default_model="gpt-4o",
        models=["gpt-4o", "gpt-4-turbo"],
    ),
    "deepseek": FlavorConfig(
        label="DeepSeek",
        key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    "xai": FlavorConfig(
        label="xAI (Grok)",
        key_env="XAI_API_KEY",
        base_url="https://api.x.ai/v1",
        default_model="grok-2-latest",
        models=["grok-2-latest", "grok-beta", "grok-vision-beta"],
    ),
    "mistral": FlavorConfig(
        label="Mistral",
        key_env="MISTRAL_API_KEY",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-large-latest",
        models=[
            "mistral-large-latest",
            "mistral-small-latest",
            "codestral-latest",
            "ministral-8b-latest",
        ],
    ),
    "perplexity": FlavorConfig(
        label="Perplexity",
        key_env="PERPLEXITY_API_KEY",
        base_url="https://api.perplexity.ai",
        default_model="llama-3.1-sonar-large-128k-online",
        models=[
            "llama-3.1-sonar-large-128k-online",
            "llama-3.1-sonar-small-128k-online",
            "llama-3.1-sonar-huge-128k-online",
        ],
    ),
    "together": FlavorConfig(
        label="Together AI",
        key_env="TOGETHER_API_KEY",
        base_url="https://api.together.xyz/v1",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        models=[
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "Qwen/Qwen2.5-72B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-V3",
        ],
    ),
    "groq": FlavorConfig(
        label="Groq",
        key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        models=[
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
    ),
    "fireworks": FlavorConfig(
        label="Fireworks AI",
        key_env="FIREWORKS_API_KEY",
        base_url="https://api.fireworks.ai/inference/v1",
        default_model="accounts/fireworks/models/llama-v3p1-405b-instruct",
        models=[
            "accounts/fireworks/models/llama-v3p1-405b-instruct",
            "accounts/fireworks/models/qwen2p5-72b-instruct",
        ],
    ),
    "cerebras": FlavorConfig(
        label="Cerebras",
        key_env="CEREBRAS_API_KEY",
        base_url="https://api.cerebras.ai/v1",
        default_model="llama-3.3-70b",
        models=["llama-3.3-70b", "llama3.1-8b"],
    ),
    "nvidia": FlavorConfig(
        label="NVIDIA NIM",
        key_env="NVIDIA_API_KEY",
        base_url="https://integrate.api.nvidia.com/v1",
        default_model="meta/llama-3.1-405b-instruct",
        models=["meta/llama-3.1-405b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"],
    ),
    "huggingface": FlavorConfig(
        label="HuggingFace Inference",
        key_env="HUGGINGFACE_API_KEY",
        base_url="https://api-inference.huggingface.co/v1",
        default_model="meta-llama/Llama-3.1-70B-Instruct",
        models=["meta-llama/Llama-3.1-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
    ),
    "lambda": FlavorConfig(
        label="Lambda Labs",
        key_env="LAMBDA_API_KEY",
        base_url="https://api.lambdalabs.com/v1",
        default_model="hermes-3-llama-3.1-405b-fp8",
        models=["hermes-3-llama-3.1-405b-fp8", "llama3.1-405b-instruct-fp8"],
    ),
    "novita": FlavorConfig(
        label="Novita AI",
        key_env="NOVITA_API_KEY",
        base_url="https://api.novita.ai/v3/openai",
        default_model="meta-llama/llama-3.1-70b-instruct",
        models=["meta-llama/llama-3.1-70b-instruct", "deepseek/deepseek-v3"],
    ),
    "custom": FlavorConfig(
        label="Custom (BYO endpoint)",
        key_env="CUSTOM_API_KEY",
        base_url=None,  # user sets CUSTOM_BASE_URL
        default_model="default",
        models=[],
    ),
}


class OpenAICompatibleProvider:
    supports_tools = True
    supports_skills = False

    def __init__(self, flavor: str = "openai"):
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise RuntimeError(
                f"Install with: pip install 'opengriffin[{flavor}]' (or any [openai-compat] extra)"
            ) from e

        cfg = FLAVORS.get(flavor)
        if cfg is None:
            raise ValueError(f"Unknown flavor: {flavor}")
        self.flavor = flavor
        self.name = cfg.label
        key = os.environ.get(cfg.key_env)
        if not key:
            raise RuntimeError(f"{cfg.key_env} not set for {cfg.label}")

        base_url = cfg.base_url
        if flavor == "azure":
            base_url = os.environ.get("AZURE_OPENAI_ENDPOINT") or base_url
        if flavor == "custom":
            base_url = os.environ.get("CUSTOM_BASE_URL")
            if not base_url:
                raise RuntimeError("CUSTOM_BASE_URL must be set when flavor=custom")

        self._client = AsyncOpenAI(api_key=key, base_url=base_url)
        self.model = os.environ.get("OPENGRIFFIN_MODEL", cfg.default_model)

    async def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        kwargs = dict(model=self.model, messages=messages)
        if tools:
            kwargs["tools"] = tools
        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return {
            "content": choice.message.content or "",
            "input_tokens": resp.usage.prompt_tokens if resp.usage else None,
            "output_tokens": resp.usage.completion_tokens if resp.usage else None,
        }
