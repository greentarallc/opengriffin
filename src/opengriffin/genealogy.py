"""Genealogy — agents inherit from parent agents and diverge over time.

Spawn a child agent (worker, pod member) from a parent. Child gets:
  - copy of parent's SOUL (forkable — child can edit independently)
  - inherits parent's skill list (subset configurable at spawn)
  - inherits MEMORY snapshot (frozen at spawn — child won't see parent's
    later additions unless explicitly synced)

The lineage is queryable: walk back to root ancestor; show all descendants.

Useful for:
  - Specialist forks: spawn 'research-griffin' from main with research skills only
  - A/B personas: parent has SOUL_A, child gets SOUL_B; compare outcomes
  - Ephemeral missions: spawn for a project, kill when done
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

GEN_FILE = Path.home() / ".opengriffin" / "genealogy.json"
AGENTS_DIR = Path.home() / ".opengriffin" / "agents"
GEN_FILE.parent.mkdir(parents=True, exist_ok=True)
AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    if not GEN_FILE.is_file():
        return {"agents": {}}
    try:
        return json.loads(GEN_FILE.read_text())
    except Exception:
        return {"agents": {}}


def _save(data: dict) -> None:
    GEN_FILE.write_text(json.dumps(data, indent=2) + "\n")


def spawn(
    name: str,
    *,
    parent_id: str | None = None,
    inherit_skills: bool = True,
    inherit_memory_snapshot: bool = True,
    soul_text: str | None = None,
) -> dict:
    aid = uuid.uuid4().hex[:8]
    adir = AGENTS_DIR / aid
    adir.mkdir(parents=True, exist_ok=True)

    parent = None
    data = _load()
    if parent_id:
        parent = data["agents"].get(parent_id)
        if parent is None:
            raise ValueError(f"parent not found: {parent_id}")

    # SOUL inheritance
    soul_path = adir / "SOUL.md"
    if soul_text is not None:
        soul_path.write_text(soul_text)
    elif parent and parent.get("soul_path") and Path(parent["soul_path"]).is_file():
        shutil.copy2(parent["soul_path"], soul_path)
    else:
        # Inherit from main SOUL
        main_soul = Path.home() / ".opengriffin" / "memories" / "SOUL.md"
        if main_soul.is_file():
            shutil.copy2(main_soul, soul_path)
        else:
            soul_path.write_text(f"# {name}\n\nNew agent. Edit my voice here.\n")

    # Memory snapshot
    snapshot = {}
    if inherit_memory_snapshot:
        for fname in ("MEMORY.md", "USER.md", "JOURNAL.md"):
            src = Path.home() / ".opengriffin" / "memories" / fname
            if src.is_file():
                dst = adir / fname
                shutil.copy2(src, dst)
                snapshot[fname] = str(dst)

    entry = {
        "id": aid,
        "name": name,
        "parent_id": parent_id,
        "inherit_skills": inherit_skills,
        "memory_snapshot": snapshot,
        "soul_path": str(soul_path),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    data["agents"][aid] = entry
    _save(data)
    return entry


def lineage(agent_id: str) -> list[dict]:
    """Walk parent chain back to root."""
    data = _load()
    chain = []
    cur = data["agents"].get(agent_id)
    while cur is not None:
        chain.append(cur)
        parent_id = cur.get("parent_id")
        cur = data["agents"].get(parent_id) if parent_id else None
    return chain


def descendants(agent_id: str) -> list[dict]:
    data = _load()
    out = []
    queue = [agent_id]
    while queue:
        cur = queue.pop(0)
        for aid, a in data["agents"].items():
            if a.get("parent_id") == cur:
                out.append(a)
                queue.append(aid)
    return out


@tool(
    "genealogy_spawn",
    "Fork a new agent from a parent (or root). Child inherits SOUL/skills/memory snapshot. Returns agent id used by other modules (workers, pods).",
    {
        "name": Annotated[str, "Agent name"],
        "parent_id": Annotated[str | None, "Parent agent id (omit for root)"],
        "soul_text": Annotated[str | None, "Override SOUL text (otherwise inherits)"],
    },
)
async def _spawn(args: dict) -> dict:
    try:
        entry = spawn(
            name=args["name"], parent_id=args.get("parent_id"), soul_text=args.get("soul_text")
        )
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(entry, indent=2)}]}


@tool(
    "genealogy_lineage",
    "Trace an agent's parent chain back to root.",
    {"agent_id": Annotated[str, "Agent id"]},
)
async def _lineage(args: dict) -> dict:
    chain = lineage(args["agent_id"])
    if not chain:
        return {"content": [{"type": "text", "text": "no such agent"}]}
    lines = [
        f"{i}: {a['id']} @{a['name']} ({a.get('created_at', '?')})" for i, a in enumerate(chain)
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "genealogy_descendants",
    "List all agents descended from a given parent.",
    {"agent_id": Annotated[str, "Parent agent id"]},
)
async def _desc(args: dict) -> dict:
    items = descendants(args["agent_id"])
    if not items:
        return {"content": [{"type": "text", "text": "no descendants"}]}
    lines = [f"{a['id']} @{a['name']} (parent {a.get('parent_id', '?')})" for a in items]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


GENEALOGY_SERVER = create_sdk_mcp_server(
    name="genealogy",
    version="1.0.0",
    tools=[_spawn, _lineage, _desc],
)
