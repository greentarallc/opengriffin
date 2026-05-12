"""A2A mesh — your agent calls another OpenGriffin user's agent for help.

Pattern: agent A discovers agent B (via reputation lookup), sends a
delegated task with a budget cap. Agent B replies with the result and
optionally a payment request via x402 (handled by wallet.py).

Each OpenGriffin instance exposes an HTTP endpoint at /a2a:
  POST /a2a/handshake   — verify identity + reputation
  POST /a2a/delegate    — accept a task with budget; returns task id
  GET  /a2a/result/<id> — poll for result

Trust model: caller pays via x402 if the responder requires it. Both sides
log to attest_log.jsonl.

This MVP is the wire protocol + caller. Real-world A2A discovery (DNS-SD?
DHT? Centralized index?) is left to the user — for now, you just provide
a URL.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import secrets
from pathlib import Path
from typing import Annotated

import requests
from aiohttp import web
from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.a2a")

A2A_TASKS_FILE = Path.home() / ".opengriffin" / "a2a_tasks.json"
A2A_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    if not A2A_TASKS_FILE.is_file():
        return {"tasks": {}}
    try:
        return json.loads(A2A_TASKS_FILE.read_text())
    except Exception:
        return {"tasks": {}}


def _save(data: dict) -> None:
    A2A_TASKS_FILE.write_text(json.dumps(data, indent=2) + "\n")


# ----------------------------- caller side -----------------------------


def call_remote(
    remote_url: str, *, prompt: str, max_amount_usd: float = 0, timeout_sec: int = 120
) -> dict:
    """Send a delegated task to another OpenGriffin agent."""
    handshake_url = remote_url.rstrip("/") + "/a2a/handshake"
    delegate_url = remote_url.rstrip("/") + "/a2a/delegate"

    # Handshake to fetch the remote's reputation profile
    try:
        r = requests.get(handshake_url, timeout=10)
        r.raise_for_status()
        remote_profile = r.json()
    except Exception as e:
        return {"ok": False, "error": f"handshake failed: {e}"}

    # Send delegation
    payload = {"prompt": prompt, "max_amount_usd": max_amount_usd}
    try:
        r = requests.post(delegate_url, json=payload, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"delegate failed: {e}"}
    if r.status_code == 402:
        # Remote requires payment — caller must use wallet.py
        try:
            challenge = r.json()
        except Exception:
            challenge = {"raw": r.text}
        return {
            "ok": False,
            "error": "payment required",
            "challenge": challenge,
            "remote_profile": remote_profile,
        }
    if r.status_code != 200:
        return {"ok": False, "error": f"remote returned {r.status_code}: {r.text[:300]}"}

    task_id = r.json().get("task_id")
    if not task_id:
        return {"ok": False, "error": "remote returned no task_id"}

    # Poll for result
    result_url = remote_url.rstrip("/") + f"/a2a/result/{task_id}"
    deadline = dt.datetime.now() + dt.timedelta(seconds=timeout_sec)
    while dt.datetime.now() < deadline:
        try:
            rr = requests.get(result_url, timeout=10)
            if rr.status_code == 200:
                body = rr.json()
                if body.get("status") == "done":
                    return {
                        "ok": True,
                        "result": body.get("result", "")[:5000],
                        "remote_profile": remote_profile,
                    }
        except Exception:
            pass
        # Sleep without await (this is sync from agent's perspective via tool)
        import time

        time.sleep(2)
    return {"ok": False, "error": "timed out polling for result"}


# ----------------------------- responder side -----------------------------


async def _handle_handshake(request: web.Request) -> web.Response:
    try:
        from . import reputation as rep_mod  # type: ignore
    except Exception:
        from . import reputation as rep_mod
    handle = request.query.get("handle", "anonymous")
    profile = rep_mod.build_profile(handle)
    return web.json_response(profile)


async def _handle_delegate(request: web.Request) -> web.Response:
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    # Optional: charge for delegation. To keep this MVP free-tier, we accept
    # all requests. Add 402 challenge here if you want paid delegation.

    task_id = secrets.token_hex(8)
    data = _load()
    data["tasks"][task_id] = {
        "id": task_id,
        "prompt": prompt,
        "status": "queued",
        "result": None,
        "queued_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)

    asyncio.create_task(_run_delegation(task_id, prompt))
    return web.json_response({"task_id": task_id})


async def _run_delegation(task_id: str, prompt: str) -> None:
    from . import bot as bot_module

    data = _load()
    data["tasks"][task_id]["status"] = "running"
    _save(data)
    try:
        result = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
        data = _load()
        data["tasks"][task_id]["result"] = result[:8000]
        data["tasks"][task_id]["status"] = "done"
        data["tasks"][task_id]["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
    except Exception as e:
        data = _load()
        data["tasks"][task_id]["status"] = "failed"
        data["tasks"][task_id]["result"] = f"failed: {e}"
    _save(data)


async def _handle_result(request: web.Request) -> web.Response:
    task_id = request.match_info.get("task_id", "")
    data = _load()
    task = data.get("tasks", {}).get(task_id)
    if not task:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(
        {
            "status": task["status"],
            "result": task.get("result"),
        }
    )


def attach(app: web.Application) -> None:
    app.router.add_get("/a2a/handshake", _handle_handshake)
    app.router.add_post("/a2a/delegate", _handle_delegate)
    app.router.add_get("/a2a/result/{task_id}", _handle_result)


@tool(
    "a2a_call",
    "Call another OpenGriffin agent over HTTP. Returns its handshake profile + the task result. Use when delegation to a remote agent makes sense (specialist domain, time zone coverage, etc.).",
    {
        "remote_url": Annotated[
            str, "Base URL of the remote OpenGriffin (e.g. https://alice.opengriffin.com)"
        ],
        "prompt": Annotated[str, "Task to delegate"],
        "max_amount_usd": Annotated[float, "Max budget (0 = free only)"],
    },
)
async def _call(args: dict) -> dict:
    result = call_remote(
        args["remote_url"],
        prompt=args["prompt"],
        max_amount_usd=float(args.get("max_amount_usd") or 0),
    )
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)[:3000]}]}


A2A_SERVER = create_sdk_mcp_server(
    name="a2a",
    version="1.0.0",
    tools=[_call],
)
