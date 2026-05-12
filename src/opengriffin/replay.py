"""Replay debugger — re-run a past session with a different model or SOUL.

Counterfactual analysis: "what would Claude Sonnet have said?", "what
would the agent with the 'terse' personality have said?". Useful for:
  - Comparing models on real workloads
  - Debugging regressions after a SOUL change
  - Sanity-checking expensive runs against a cheaper model

Loads a past session's user messages (Claude Code stores transcripts
under ~/.claude/projects/<encoded-cwd>/<session_id>.jsonl), replays them
through a fresh ClaudeAgentOptions with overrides, and emits a side-by-side
comparison.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)

log = logging.getLogger("opengriffin.replay")

PROJECTS = Path.home() / ".claude" / "projects" / "-Users-macmini"
REPLAY_LOG = Path.home() / ".opengriffin" / "replay_log.jsonl"
REPLAY_LOG.parent.mkdir(parents=True, exist_ok=True)


def _user_messages(session_id: str) -> list[str]:
    f = PROJECTS / f"{session_id}.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            msg = json.loads(line)
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                out.append(content)
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        out.append(c.get("text", ""))
        except Exception:
            continue
    return out


async def replay(
    session_id: str, *, soul_text: str | None = None, model: str | None = None
) -> dict:
    """Replay user messages from session_id with overrides; return new transcript."""
    msgs = _user_messages(session_id)
    if not msgs:
        return {"ok": False, "error": f"no user messages in session {session_id}"}

    append = "(replay)"
    if soul_text:
        append += "\n\n# Replay personality override\n" + soul_text
    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": append},
        permission_mode="bypassPermissions",
        cwd=str(Path.home()),
        model=model,  # type: ignore — SDK accepts None
        include_partial_messages=False,
    )
    transcript = []
    new_session_id = None
    async with ClaudeSDKClient(options=options) as client:
        for u in msgs[:6]:  # cap to 6 turns to bound cost
            await client.query(u)
            chunks = []
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, TextBlock):
                            chunks.append(b.text)
                elif isinstance(msg, ResultMessage):
                    new_session_id = msg.session_id
                    break
            transcript.append({"user": u, "assistant": "".join(chunks).strip()[:1000]})

    record = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "original_session": session_id,
        "new_session": new_session_id,
        "model_override": model,
        "soul_override": bool(soul_text),
        "turns": len(transcript),
    }
    with REPLAY_LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return {"ok": True, "transcript": transcript, "record": record}


@tool(
    "replay_session",
    "Re-run a past session with a different model or SOUL. Returns the new transcript so you can diff it against the original.",
    {
        "session_id": Annotated[str, "Original session id"],
        "soul_text": Annotated[str | None, "Override SOUL text"],
        "model": Annotated[str | None, "Override model id"],
    },
)
async def _replay(args: dict) -> dict:
    result = await replay(
        args["session_id"], soul_text=args.get("soul_text"), model=args.get("model")
    )
    if not result.get("ok"):
        return {"content": [{"type": "text", "text": str(result)}], "is_error": True}
    out = []
    for t in result["transcript"]:
        out.append(f"USER: {t['user'][:200]}\nASSISTANT: {t['assistant'][:600]}")
    return {"content": [{"type": "text", "text": "\n\n---\n\n".join(out)}]}


REPLAY_SERVER = create_sdk_mcp_server(
    name="replay",
    version="1.0.0",
    tools=[_replay],
)
