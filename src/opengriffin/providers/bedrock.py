"""AWS Bedrock provider — Claude, Llama, Mistral, etc. via AWS."""

from __future__ import annotations

import os


class BedrockProvider:
    name = "AWS Bedrock"
    supports_tools = True
    supports_skills = False

    def __init__(self, model: str | None = None):
        try:
            import boto3  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Install with: pip install 'opengriffin[bedrock]'") from e
        import boto3

        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self._client = boto3.client("bedrock-runtime", region_name=region)
        self.model = model or os.environ.get(
            "OPENGRIFFIN_MODEL", "us.anthropic.claude-opus-4-7-v1:0"
        )

    async def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        # Use converse API (model-agnostic)
        bedrock_messages = [
            {"role": m["role"], "content": [{"text": m["content"]}]}
            for m in messages
            if m["role"] in ("user", "assistant")
        ]
        import asyncio

        resp = await asyncio.to_thread(
            self._client.converse,
            modelId=self.model,
            messages=bedrock_messages,
        )
        text = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage", {})
        return {
            "content": text,
            "input_tokens": usage.get("inputTokens"),
            "output_tokens": usage.get("outputTokens"),
        }
