"""Claude provider — full power via Claude Agent SDK.

Uses the local Claude Code CLI bundled with `claude-agent-sdk`. Inherits
Claude Max OAuth credentials automatically when present (`~/.claude/.credentials.json`),
or pay-per-token via `ANTHROPIC_API_KEY`.

This is the recommended provider — only one with skills, MCP, hooks, and
session persistence.
"""

from __future__ import annotations

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient


class ClaudeProvider:
    name = "Claude (Agent SDK)"
    supports_tools = True
    supports_skills = True

    async def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        # Convenience for non-bot callers who just want a one-shot chat.
        # The bot itself uses ClaudeSDKClient directly with full options.
        prompt = messages[-1]["content"] if messages else ""
        chunks: list[str] = []
        async with ClaudeSDKClient(options=ClaudeAgentOptions()) as client:
            await client.query(prompt)
            from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, TextBlock):
                            chunks.append(b.text)
                elif isinstance(msg, ResultMessage):
                    return {
                        "content": "".join(chunks).strip(),
                        "session_id": msg.session_id,
                        "cost_usd": getattr(msg, "total_cost_usd", None),
                    }
        return {"content": "".join(chunks).strip()}
