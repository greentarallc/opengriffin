"""Agent Pods — multiple bot identities sharing memory, talking to each other.

Add `@research-griffin` and `@coding-griffin` to a Telegram group; each is
a separate bot persona with its own SOUL.md but shared MEMORY.md/USER.md.
When mentioned, an agent runs a turn. When two agents are addressed, they
take turns until the conversation converges (consensus protocol).

Storage:
  pods.json — {"pods": {"<pod_name>": {"agents": [...], "convergence_threshold": 3}}}
  Each agent has: {name, soul (path to SOUL file), provider, model}
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Optional

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.pods")

PODS_FILE = Path.home() / ".opengriffin" / "pods.json"
PODS_FILE.parent.mkdir(parents=True, exist_ok=True)

MAX_TURNS = 8           # avoid infinite agent-back-and-forth
CONVERGENCE_KEYWORDS = ("agreed", "agree", "let's go with", "ship it", "lgtm", "yes that's right")


def _load() -> dict:
    if not PODS_FILE.is_file():
        return {"pods": {}}
    try:
        return json.loads(PODS_FILE.read_text())
    except Exception:
        return {"pods": {}}


def _save(data: dict) -> None:
    PODS_FILE.write_text(json.dumps(data, indent=2) + "\n")


# ----------------------------- pod orchestration -----------------------------


async def run_pod_turn(pod_name: str, user_message: str, chat_id: int) -> str:
    """Run a multi-agent turn. Each agent in the pod responds in sequence,
    seeing the prior agents' replies as additional context. Stops when:
      - all agents have spoken at least once AND
      - a convergence keyword appears in the latest agent's response, OR
      - MAX_TURNS hit.
    """
    from . import bot as bot_module  # noqa
    pods = _load().get("pods", {})
    pod = pods.get(pod_name)
    if pod is None:
        return f"unknown pod: {pod_name}"
    agents = pod.get("agents", [])
    if not agents:
        return f"pod {pod_name} has no agents"

    transcript: list[dict] = [{"speaker": "user", "text": user_message}]
    spoken: set[str] = set()
    last_text = ""

    for turn in range(MAX_TURNS):
        # Pick next agent (round-robin)
        agent = agents[turn % len(agents)]
        # Build the system-prompt-style instruction
        soul_addendum = ""
        soul_path = agent.get("soul")
        if soul_path and Path(soul_path).is_file():
            soul_addendum = "\n\nYour persona:\n" + Path(soul_path).read_text()

        history = "\n".join(
            f"@{x['speaker']}: {x['text']}" for x in transcript
        )
        prompt = (
            f"You are agent @{agent['name']} in a group conversation. "
            f"{soul_addendum}\n\n"
            "Other agents in the pod: " + ", ".join("@" + a["name"] for a in agents if a["name"] != agent["name"]) + ".\n\n"
            f"Conversation so far:\n{history}\n\n"
            f"Reply as @{agent['name']}. If you agree with the latest message and "
            f"have nothing to add, end your reply with the literal token 'AGREED'."
        )
        try:
            reply = await bot_module.ask_claude_with_progress(chat_id, prompt, None, status_msg_id=None)
        except Exception as e:
            log.exception("pod turn failed")
            return f"pod error on turn {turn}: {e}"

        transcript.append({"speaker": agent["name"], "text": reply})
        spoken.add(agent["name"])
        last_text = reply.lower()

        # Convergence: all agents spoken AND signal of agreement
        if len(spoken) >= len(agents) and (
            "agreed" in last_text[-200:] or
            any(k in last_text for k in CONVERGENCE_KEYWORDS)
        ):
            break

    return "\n\n".join(f"@{x['speaker']}: {x['text']}" for x in transcript)


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "pod_create",
    "Create an Agent Pod with multiple agent personas. Each agent has its own SOUL but shares MEMORY/USER. Use when the user wants several specialist personas to discuss a problem.",
    {
        "name": Annotated[str, "Pod name (e.g. 'eng-pod')"],
        "agents": Annotated[
            str,
            "JSON list. Each agent: {name, soul_path (optional), provider (optional), model (optional)}. Example: '[{\"name\":\"researcher\"},{\"name\":\"engineer\"}]'",
        ],
    },
)
async def _pod_create(args: dict) -> dict:
    try:
        agents = json.loads(args["agents"])
        assert isinstance(agents, list) and agents
    except Exception as e:
        return {"content": [{"type": "text", "text": f"agents JSON invalid: {e}"}], "is_error": True}
    data = _load()
    data["pods"][args["name"]] = {
        "agents": agents,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)
    return {"content": [{"type": "text", "text": f"pod {args['name']} created with {len(agents)} agents"}]}


@tool(
    "pod_run",
    "Run an Agent Pod conversation on a topic. Returns the multi-agent transcript ending in convergence or MAX_TURNS.",
    {
        "name": Annotated[str, "Pod name"],
        "message": Annotated[str, "The topic / user message"],
    },
)
async def _pod_run(args: dict) -> dict:
    transcript = await run_pod_turn(args["name"], args["message"], chat_id=0)
    return {"content": [{"type": "text", "text": transcript}]}


@tool(
    "pod_list",
    "List all configured Agent Pods.",
    {},
)
async def _pod_list(args: dict) -> dict:
    pods = _load().get("pods", {})
    if not pods:
        return {"content": [{"type": "text", "text": "(no pods)"}]}
    lines = [f"{name} — {len(p['agents'])} agents: {', '.join(a['name'] for a in p['agents'])}"
             for name, p in pods.items()]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


PODS_SERVER = create_sdk_mcp_server(
    name="pods",
    version="1.0.0",
    tools=[_pod_create, _pod_run, _pod_list],
)
