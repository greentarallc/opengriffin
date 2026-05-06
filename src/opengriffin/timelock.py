"""Time-locked actions — agent commits to do X at a future time, can't reverse without veto.

Pattern: agent or user proposes "at 2026-05-10T15:00 send email Y to Z".
The action is locked; ID returned. Before execution time, the user can
veto via Telegram (`/veto <id>`). At execution time, if not vetoed, the
action runs irreversibly.

This is useful for:
  - Self-imposed deadlines ("if I don't ship by Friday, post the apology")
  - Scheduled commits the agent shouldn't be talked out of
  - Dead-man delivery (combined with deadman.py)

Storage: timelock.json + APScheduler dated triggers.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from pathlib import Path
from typing import Annotated, Optional

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.timelock")

LOCK_FILE = Path.home() / ".opengriffin" / "timelock.json"
LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    if not LOCK_FILE.is_file():
        return {"locks": []}
    try:
        return json.loads(LOCK_FILE.read_text())
    except Exception:
        return {"locks": []}


def _save(data: dict) -> None:
    LOCK_FILE.write_text(json.dumps(data, indent=2) + "\n")


def lock(*, when_iso: str, action_kind: str, payload: dict, note: str = "") -> dict:
    """Create a new time-locked action."""
    when = dt.datetime.fromisoformat(when_iso)
    if when <= dt.datetime.now():
        raise ValueError("when must be in the future")
    entry = {
        "id": uuid.uuid4().hex[:8],
        "when_iso": when_iso,
        "action_kind": action_kind,   # "send" | "agent_run" | "shell"
        "payload": payload,
        "note": note,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "vetoed": False,
        "executed": False,
        "execution_result": None,
    }
    data = _load()
    data["locks"].append(entry)
    _save(data)
    return entry


def veto(lock_id: str) -> bool:
    data = _load()
    for e in data["locks"]:
        if e["id"] == lock_id and not e.get("executed"):
            e["vetoed"] = True
            _save(data)
            return True
    return False


def list_active() -> list[dict]:
    data = _load()
    now = dt.datetime.now()
    return [e for e in data["locks"] if not e.get("executed") and not e.get("vetoed")
            and dt.datetime.fromisoformat(e["when_iso"]) > now]


async def fire(lock_id: str) -> str:
    """Called by APScheduler at the lock's time. Runs unless vetoed."""
    from . import bot as bot_module
    from botctx import CTX
    data = _load()
    entry = next((e for e in data["locks"] if e["id"] == lock_id), None)
    if entry is None:
        return f"lock {lock_id} not found"
    if entry.get("vetoed"):
        return f"lock {lock_id} vetoed; skipping"
    if entry.get("executed"):
        return f"lock {lock_id} already executed"

    kind = entry["action_kind"]
    payload = entry.get("payload") or {}
    result = "?"
    try:
        if kind == "send":
            chat = payload.get("chat_id") or CTX.home_chat_id
            text = payload.get("text", "(empty)")
            if CTX.bot:
                await CTX.bot.send_message(chat_id=chat, text=text)
            result = "sent"
        elif kind == "agent_run":
            prompt = payload.get("prompt", "")
            result = (await bot_module.ask_claude_with_progress(0, prompt, CTX.bot, status_msg_id=None))[:500]
        elif kind == "shell":
            import subprocess
            cmd = payload.get("command", "")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            result = f"exit={r.returncode}\n{r.stdout[:1000]}{r.stderr[:500]}"
        else:
            result = f"unknown action_kind: {kind}"
    except Exception as e:
        result = f"failed: {e}"

    entry["executed"] = True
    entry["execution_result"] = result[:1500]
    entry["executed_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _save(data)
    return result


def install_into_scheduler(scheduler) -> int:
    """Schedule firing for every active timelock."""
    from apscheduler.triggers.date import DateTrigger
    n = 0
    for e in list_active():
        try:
            scheduler.add_job(
                fire,
                trigger=DateTrigger(run_date=dt.datetime.fromisoformat(e["when_iso"])),
                args=[e["id"]],
                id=f"timelock:{e['id']}",
                name=f"timelock:{e['id']}",
                replace_existing=True,
            )
            n += 1
        except Exception:
            log.exception("timelock schedule failed for %s", e["id"])
    return n


@tool(
    "timelock_create",
    "Create a time-locked action. Will fire at when_iso unless vetoed via /veto. action_kind one of: 'send' (payload: {chat_id?, text}), 'agent_run' (payload: {prompt}), 'shell' (payload: {command}).",
    {
        "when_iso": Annotated[str, "ISO 8601 timestamp (e.g. '2026-05-10T15:00')"],
        "action_kind": Annotated[str, "send | agent_run | shell"],
        "payload_json": Annotated[str, "JSON payload for the action"],
        "note": Annotated[Optional[str], "Why this lock exists"],
    },
)
async def _create(args: dict) -> dict:
    payload = json.loads(args["payload_json"])
    entry = lock(when_iso=args["when_iso"], action_kind=args["action_kind"], payload=payload, note=args.get("note") or "")
    # Schedule it now
    from botctx import CTX
    if CTX.scheduler:
        from apscheduler.triggers.date import DateTrigger
        CTX.scheduler.add_job(
            fire,
            trigger=DateTrigger(run_date=dt.datetime.fromisoformat(entry["when_iso"])),
            args=[entry["id"]],
            id=f"timelock:{entry['id']}",
            name=f"timelock:{entry['id']}",
            replace_existing=True,
        )
    return {"content": [{"type": "text", "text": json.dumps(entry, indent=2)}]}


@tool(
    "timelock_veto",
    "Veto a pending time-locked action.",
    {"id": Annotated[str, "Lock id"]},
)
async def _veto(args: dict) -> dict:
    ok = veto(args["id"])
    return {"content": [{"type": "text", "text": "vetoed" if ok else "not found / already executed"}], "is_error": not ok}


@tool(
    "timelock_list",
    "List active (pending, un-vetoed) time-locked actions.",
    {},
)
async def _list(args: dict) -> dict:
    items = list_active()
    if not items:
        return {"content": [{"type": "text", "text": "(no active locks)"}]}
    lines = [f"{e['id']} @ {e['when_iso']} — {e['action_kind']} — {e.get('note','')[:80]}" for e in items]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


TIMELOCK_SERVER = create_sdk_mcp_server(
    name="timelock",
    version="1.0.0",
    tools=[_create, _veto, _list],
)
