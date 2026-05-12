"""Lightweight kanban board: JSON-backed task list with MCP tools and a
Telegram `/kanban` view. Tasks have id, title, status (todo/doing/done),
assignee, body. The agent can create/claim/complete/list and "dispatch" —
which runs the task body as a Claude prompt and stores the result.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

KANBAN_FILE = Path(__file__).resolve().parent / "kanban.json"

VALID_STATUS = ("todo", "doing", "done", "blocked")


def _load() -> dict:
    if not KANBAN_FILE.exists():
        return {"tasks": []}
    return json.loads(KANBAN_FILE.read_text())


def _save(data: dict) -> None:
    KANBAN_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def _find(data: dict, task_id: str) -> dict | None:
    return next((t for t in data["tasks"] if t["id"] == task_id), None)


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


@tool(
    "kanban_create",
    "Create a new kanban task in status 'todo'. Returns the task id.",
    {
        "title": Annotated[str, "Short task title"],
        "body": Annotated[str, "Full task description / instructions"],
        "assignee": Annotated[str | None, "Optional assignee name (defaults to 'unassigned')"],
    },
)
async def _kanban_create(args: dict) -> dict:
    data = _load()
    task = {
        "id": _short_id(),
        "title": args["title"],
        "body": args["body"],
        "status": "todo",
        "assignee": args.get("assignee") or "unassigned",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "result": None,
    }
    data["tasks"].append(task)
    _save(data)
    return _ok(f"created {task['id']}: {task['title']}")


@tool(
    "kanban_list",
    "List kanban tasks. Optionally filter by status (todo/doing/done/blocked) or assignee.",
    {
        "status": Annotated[str | None, "Filter by status"],
        "assignee": Annotated[str | None, "Filter by assignee"],
    },
)
async def _kanban_list(args: dict) -> dict:
    data = _load()
    tasks = data["tasks"]
    if args.get("status"):
        tasks = [t for t in tasks if t["status"] == args["status"]]
    if args.get("assignee"):
        tasks = [t for t in tasks if t["assignee"] == args["assignee"]]
    if not tasks:
        return _ok("(no matching tasks)")
    lines = [f"{t['id']} [{t['status']}] {t['assignee']} — {t['title']}" for t in tasks]
    return _ok("\n".join(lines))


@tool(
    "kanban_claim",
    "Claim a task — sets assignee and moves status to 'doing'.",
    {
        "id": Annotated[str, "Task id"],
        "assignee": Annotated[str, "Who is taking it"],
    },
)
async def _kanban_claim(args: dict) -> dict:
    data = _load()
    t = _find(data, args["id"])
    if t is None:
        return _err(f"no such task: {args['id']}")
    t["assignee"] = args["assignee"]
    t["status"] = "doing"
    t["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save(data)
    return _ok(f"claimed {t['id']} for {t['assignee']}")


@tool(
    "kanban_complete",
    "Mark a task done. Optionally store result text on the task.",
    {
        "id": Annotated[str, "Task id"],
        "result": Annotated[str | None, "Optional result/output to store on the task"],
    },
)
async def _kanban_complete(args: dict) -> dict:
    data = _load()
    t = _find(data, args["id"])
    if t is None:
        return _err(f"no such task: {args['id']}")
    t["status"] = "done"
    t["result"] = args.get("result") or t.get("result")
    t["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save(data)
    return _ok(f"completed {t['id']}")


@tool(
    "kanban_block",
    "Mark a task blocked with a reason.",
    {"id": Annotated[str, "Task id"], "reason": Annotated[str, "Why blocked"]},
)
async def _kanban_block(args: dict) -> dict:
    data = _load()
    t = _find(data, args["id"])
    if t is None:
        return _err(f"no such task: {args['id']}")
    t["status"] = "blocked"
    t["block_reason"] = args["reason"]
    t["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save(data)
    return _ok(f"blocked {t['id']}: {args['reason']}")


@tool(
    "kanban_get",
    "Get full details of a task including its body and result.",
    {"id": Annotated[str, "Task id"]},
)
async def _kanban_get(args: dict) -> dict:
    data = _load()
    t = _find(data, args["id"])
    if t is None:
        return _err(f"no such task: {args['id']}")
    return _ok(json.dumps(t, indent=2))


@tool(
    "kanban_remove",
    "Delete a task.",
    {"id": Annotated[str, "Task id"]},
)
async def _kanban_remove(args: dict) -> dict:
    data = _load()
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != args["id"]]
    if len(data["tasks"]) == before:
        return _err(f"no such task: {args['id']}")
    _save(data)
    return _ok(f"removed {args['id']}")


KANBAN_SERVER = create_sdk_mcp_server(
    name="kanban",
    version="1.0.0",
    tools=[
        _kanban_create,
        _kanban_list,
        _kanban_claim,
        _kanban_complete,
        _kanban_block,
        _kanban_get,
        _kanban_remove,
    ],
)


# --- view helpers for the /kanban Telegram command ---


def render_board() -> str:
    data = _load()
    if not data["tasks"]:
        return "_(empty board)_"
    by_status: dict[str, list[dict]] = {s: [] for s in VALID_STATUS}
    for t in data["tasks"]:
        by_status.setdefault(t["status"], []).append(t)
    parts = []
    for status in VALID_STATUS:
        items = by_status.get(status, [])
        if not items:
            continue
        parts.append(f"*{status.upper()}*")
        for t in items:
            parts.append(f"• `{t['id']}` {t['title']} _(@{t['assignee']})_")
        parts.append("")
    return "\n".join(parts).strip() or "_(empty board)_"
