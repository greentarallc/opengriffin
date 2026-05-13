"""Worker pool — long-running background agents not bound to a chat.

Each worker has:
  - id, name, role (e.g. "research", "engineering", "ops")
  - SOUL pointer (own personality)
  - task queue (FIFO, persisted to disk)
  - status (idle | working | sleeping | dead)
  - heartbeat (last seen)
  - parent_id (for genealogy)

Workers run as asyncio tasks inside the bot process. They poll their queue
every N seconds, claim a task, run it, write the result to a results file,
and check in to the home chat at configurable intervals.

This gives you a "team of developers" pattern. A user can:
  - "Spawn a research worker named atlas to compile a report on X"
  - "Hand off the kanban research-pod tasks to atlas"
  - "Give me a status report from all workers"
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import uuid
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.workers")

WORKERS_DIR = Path.home() / ".opengriffin" / "workers"
WORKERS_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY = WORKERS_DIR / "registry.json"

# In-process handle to running worker tasks
_running: dict[str, asyncio.Task] = {}


def _load_registry() -> dict:
    if not REGISTRY.is_file():
        return {"workers": {}}
    try:
        return json.loads(REGISTRY.read_text())
    except Exception:
        return {"workers": {}}


def _save_registry(data: dict) -> None:
    REGISTRY.write_text(json.dumps(data, indent=2) + "\n")


def _worker_dir(worker_id: str) -> Path:
    p = WORKERS_DIR / worker_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _queue_path(worker_id: str) -> Path:
    return _worker_dir(worker_id) / "queue.jsonl"


def _results_path(worker_id: str) -> Path:
    return _worker_dir(worker_id) / "results.jsonl"


def list_workers() -> list[dict]:
    return list(_load_registry().get("workers", {}).values())


def create(
    name: str,
    role: str,
    *,
    soul: str | None = None,
    parent_id: str | None = None,
    checkin_interval_min: int = 60,
) -> dict:
    """Register a worker. Doesn't start it — call `start()`."""
    wid = uuid.uuid4().hex[:8]
    entry = {
        "id": wid,
        "name": name,
        "role": role,
        "soul": soul,
        "parent_id": parent_id,
        "checkin_interval_min": checkin_interval_min,
        "status": "idle",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "last_heartbeat": None,
        "tasks_completed": 0,
        "tasks_failed": 0,
    }
    data = _load_registry()
    data["workers"][wid] = entry
    _save_registry(data)
    _queue_path(wid).touch()
    _results_path(wid).touch()
    return entry


def enqueue(worker_id: str, task_text: str, *, priority: int = 5) -> str:
    """Add a task to a worker's queue. Returns task id."""
    tid = uuid.uuid4().hex[:8]
    entry = {
        "task_id": tid,
        "text": task_text,
        "priority": priority,
        "queued_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with _queue_path(worker_id).open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return tid


def _read_queue(worker_id: str) -> list[dict]:
    p = _queue_path(worker_id)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _rewrite_queue(worker_id: str, items: list[dict]) -> None:
    with _queue_path(worker_id).open("w") as fh:
        for x in items:
            fh.write(json.dumps(x) + "\n")


async def _run_loop(worker_id: str) -> None:
    """The actual worker loop. Polls queue, runs tasks, writes results,
    checks in periodically."""
    from . import bot as bot_module  # noqa
    from botctx import CTX

    last_checkin = dt.datetime.now()
    while True:
        # Update heartbeat
        data = _load_registry()
        worker = data["workers"].get(worker_id)
        if worker is None or worker.get("status") == "dead":
            log.info("worker %s exiting", worker_id)
            return
        worker["last_heartbeat"] = dt.datetime.now().isoformat(timespec="seconds")

        # Check queue
        queue = _read_queue(worker_id)
        queue.sort(key=lambda x: (-x.get("priority", 5), x.get("queued_at", "")))
        if queue:
            task = queue[0]
            remaining = queue[1:]
            _rewrite_queue(worker_id, remaining)
            worker["status"] = "working"
            _save_registry(data)
            log.info("worker %s starting task %s", worker_id, task["task_id"])

            soul_addendum = ""
            if worker.get("soul") and Path(worker["soul"]).is_file():
                soul_addendum = "\n\nYour persona:\n" + Path(worker["soul"]).read_text()
            prompt = (
                f"You are worker @{worker['name']} (role: {worker['role']}). "
                f"{soul_addendum}\n\n"
                f"Task: {task['text']}\n\n"
                "Complete the task. Be terse. Final reply must be the deliverable."
            )

            started = dt.datetime.now()
            try:
                result_text = await bot_module.ask_claude_with_progress(
                    chat_id=0, prompt=prompt, bot=CTX.bot, status_msg_id=None
                )
                ok = True
            except Exception as e:
                result_text = f"failed: {e}"
                ok = False
            finished = dt.datetime.now()

            with _results_path(worker_id).open("a") as fh:
                fh.write(
                    json.dumps(
                        {
                            "task_id": task["task_id"],
                            "task_text": task["text"],
                            "result": result_text[:8000],
                            "started_at": started.isoformat(timespec="seconds"),
                            "finished_at": finished.isoformat(timespec="seconds"),
                            "duration_sec": round((finished - started).total_seconds(), 1),
                            "ok": ok,
                        }
                    )
                    + "\n"
                )

            data = _load_registry()
            worker = data["workers"].get(worker_id) or worker
            if ok:
                worker["tasks_completed"] = worker.get("tasks_completed", 0) + 1
            else:
                worker["tasks_failed"] = worker.get("tasks_failed", 0) + 1
            worker["status"] = "idle"
            _save_registry(data)

            # Check-in if enough time has passed
            if (dt.datetime.now() - last_checkin).total_seconds() >= worker.get(
                "checkin_interval_min", 60
            ) * 60:
                if CTX.bot and CTX.home_chat_id:
                    summary = (
                        f"📋 Worker @{worker['name']} ({worker['role']}): "
                        f"completed task {task['task_id']} ({'ok' if ok else 'failed'}) "
                        f"in {round((finished - started).total_seconds())}s. "
                        f"Queue: {len(remaining)} pending."
                    )
                    with contextlib.suppress(Exception):
                        await CTX.bot.send_message(chat_id=CTX.home_chat_id, text=summary)
                last_checkin = dt.datetime.now()
        else:
            data = _load_registry()
            worker = data["workers"].get(worker_id)
            if worker:
                worker["status"] = "idle"
                _save_registry(data)
            await asyncio.sleep(15)
            continue

        await asyncio.sleep(2)


async def start(worker_id: str) -> bool:
    """Spawn the worker's loop as a background task in the current event loop."""
    data = _load_registry()
    if worker_id not in data["workers"]:
        return False
    if worker_id in _running and not _running[worker_id].done():
        return True  # already running
    task = asyncio.create_task(_run_loop(worker_id))
    _running[worker_id] = task
    return True


def kill(worker_id: str) -> bool:
    """Mark worker dead — its loop will exit on next heartbeat tick."""
    data = _load_registry()
    if worker_id not in data["workers"]:
        return False
    data["workers"][worker_id]["status"] = "dead"
    _save_registry(data)
    if worker_id in _running:
        _running[worker_id].cancel()
        del _running[worker_id]
    return True


def status_all() -> str:
    workers = list_workers()
    if not workers:
        return "(no workers)"
    lines = []
    for w in workers:
        if w.get("status") == "dead":
            continue
        q = len(_read_queue(w["id"]))
        lines.append(
            f"{w['id']} @{w['name']} ({w['role']}) — {w['status']} — "
            f"queue={q} done={w.get('tasks_completed', 0)} failed={w.get('tasks_failed', 0)} "
            f"hb={w.get('last_heartbeat') or '—'}"
        )
    return "\n".join(lines)


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "worker_spawn",
    "Spawn a long-running background worker agent. They run inside the bot process, claiming tasks from a queue. Use when the user wants a 'team' approach — e.g. 'spawn a research worker named atlas'.",
    {
        "name": Annotated[str, "Worker name (e.g. 'atlas')"],
        "role": Annotated[str, "Role description ('research', 'engineering', 'ops')"],
        "soul_path": Annotated[str | None, "Optional path to a SOUL.md persona file"],
        "checkin_interval_min": Annotated[
            int | None, "Minutes between Telegram check-ins (default 60)"
        ],
    },
)
async def _spawn(args: dict) -> dict:
    entry = create(
        name=args["name"],
        role=args["role"],
        soul=args.get("soul_path"),
        checkin_interval_min=int(args.get("checkin_interval_min") or 60),
    )
    await start(entry["id"])
    return {
        "content": [
            {
                "type": "text",
                "text": f"spawned worker {entry['id']} @{entry['name']} ({entry['role']})",
            }
        ]
    }


@tool(
    "worker_assign",
    "Assign a task to a worker's queue.",
    {
        "worker_id": Annotated[str, "Worker id (or name with @ prefix)"],
        "task": Annotated[str, "Full task description"],
        "priority": Annotated[int | None, "1-10, higher = sooner (default 5)"],
    },
)
async def _assign(args: dict) -> dict:
    wid = args["worker_id"].lstrip("@")
    if not wid.isalnum() or len(wid) != 8:
        # Lookup by name
        for w in list_workers():
            if w["name"] == wid:
                wid = w["id"]
                break
        else:
            return {
                "content": [{"type": "text", "text": f"no worker: {args['worker_id']}"}],
                "is_error": True,
            }
    tid = enqueue(wid, args["task"], priority=int(args.get("priority") or 5))
    return {"content": [{"type": "text", "text": f"queued task {tid} on worker {wid}"}]}


@tool(
    "worker_status",
    "Show all running workers with their queue depth, completion stats, last heartbeat.",
    {},
)
async def _status(args: dict) -> dict:
    return {"content": [{"type": "text", "text": status_all()}]}


@tool(
    "worker_kill",
    "Stop a worker. It will exit cleanly after finishing the current task.",
    {"worker_id": Annotated[str, "Worker id"]},
)
async def _kill(args: dict) -> dict:
    ok = kill(args["worker_id"])
    return {
        "content": [{"type": "text", "text": "killed" if ok else "not found"}],
        "is_error": not ok,
    }


@tool(
    "worker_results",
    "Read the last N results from a worker's results log.",
    {
        "worker_id": Annotated[str, "Worker id"],
        "n": Annotated[int | None, "How many results (default 5)"],
    },
)
async def _results(args: dict) -> dict:
    wid = args["worker_id"]
    p = _results_path(wid)
    if not p.is_file():
        return {"content": [{"type": "text", "text": "no results"}]}
    n = int(args.get("n") or 5)
    lines = p.read_text().splitlines()[-n:]
    out = []
    for line in lines:
        try:
            r = json.loads(line)
            out.append(
                f"[{r.get('finished_at')}] {r.get('task_text', '')[:80]} → {('ok' if r.get('ok') else 'fail')}: {r.get('result', '')[:300]}"
            )
        except Exception:
            continue
    return {"content": [{"type": "text", "text": "\n\n".join(out)}]}


WORKERS_SERVER = create_sdk_mcp_server(
    name="workers",
    version="1.0.0",
    tools=[_spawn, _assign, _status, _kill, _results],
)


# ----------------------------- bootstrap on bot startup -----------------------------


async def restart_persisted() -> int:
    """On bot startup: re-launch the loop for every non-dead worker.

    Their queues are preserved on disk, so nothing is lost across restarts.
    """
    n = 0
    for w in list_workers():
        if w.get("status") not in ("dead",):
            try:
                await start(w["id"])
                n += 1
            except Exception:
                log.exception("failed to restart worker %s", w.get("id"))
    return n
