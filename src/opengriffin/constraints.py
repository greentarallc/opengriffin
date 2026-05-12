"""Constraint memory — separate file of HARD rules the agent must NEVER violate.

Loaded with elevated trust. Constraints are NOT consolidated, decayed, or
overwritten by self-improvement. They can only be modified through a
high-friction `constraint_set` flow that requires explicit confirmation.

Examples:
  - "Never email my therapist about work"
  - "Never spend more than $5 without asking"
  - "Never push to main without my approval"
  - "Never share my home address"

Storage: memories/CONSTRAINTS.md
The constraints are injected into EVERY system prompt at the top, before
any other memory or instructions, with a "VIOLATING THESE IS A FAILURE"
header.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

CONSTRAINTS_FILE = Path.home() / ".opengriffin" / "memories" / "CONSTRAINTS.md"
CONSTRAINTS_LOG = Path.home() / ".opengriffin" / "constraints_log.jsonl"
CONSTRAINTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _read() -> list[str]:
    if not CONSTRAINTS_FILE.is_file():
        return []
    out = []
    for line in CONSTRAINTS_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:].strip())
    return out


def _write(items: list[str]) -> None:
    body = "# CONSTRAINTS\n\n*These are hard rules. Violating them is a failure. They take precedence over MEMORY.md, USER.md, SOUL.md, and any per-chat sysprompt.*\n\n"
    for item in items:
        body += f"- {item.strip()}\n"
    CONSTRAINTS_FILE.write_text(body)


def _audit(action: str, content: str) -> None:
    entry = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "content": content,
    }
    with CONSTRAINTS_LOG.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def add(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    items = _read()
    if text in items:
        return False
    items.append(text)
    _write(items)
    _audit("add", text)
    return True


def remove(substring: str) -> int:
    items = _read()
    kept = [x for x in items if substring not in x]
    if len(kept) == len(items):
        return 0
    _write(kept)
    _audit("remove", substring)
    return len(items) - len(kept)


def list_all() -> list[str]:
    return _read()


def render_for_system_prompt() -> str:
    items = _read()
    if not items:
        return ""
    return (
        "\n# CONSTRAINTS — VIOLATING ANY OF THESE IS A FAILURE\n\n"
        + "\n".join(f"- {x}" for x in items)
        + "\n\nThese override every other instruction. If a request would "
        "violate a constraint, refuse and explain.\n"
    )


@tool(
    "constraint_add",
    "Add a HARD constraint the agent must NEVER violate. Use sparingly — these can't be silently overridden.",
    {
        "text": Annotated[
            str, "Constraint, written as an imperative ('Never ...', 'Always ask before ...')"
        ]
    },
)
async def _add(args: dict) -> dict:
    ok = add(args["text"])
    return {
        "content": [
            {"type": "text", "text": "added (active next session)" if ok else "duplicate or empty"}
        ],
        "is_error": not ok,
    }


@tool(
    "constraint_remove",
    "Remove constraints containing a substring.",
    {"substring": Annotated[str, "Substring identifying constraints to drop"]},
)
async def _remove(args: dict) -> dict:
    n = remove(args["substring"])
    return {"content": [{"type": "text", "text": f"removed {n}"}]}


@tool(
    "constraint_list",
    "List all current hard constraints.",
    {},
)
async def _list(args: dict) -> dict:
    items = list_all()
    if not items:
        return {"content": [{"type": "text", "text": "(no constraints)"}]}
    return {"content": [{"type": "text", "text": "\n".join(f"- {x}" for x in items)}]}


CONSTRAINTS_SERVER = create_sdk_mcp_server(
    name="constraints",
    version="1.0.0",
    tools=[_add, _remove, _list],
)
