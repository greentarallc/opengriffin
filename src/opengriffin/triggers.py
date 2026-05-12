"""Ambient Trigger Mesh — composable signal → predicate → action DAG.

Triggers fire from any of:
  - cron expression (uses APScheduler, same as cron jobs)
  - webhook event arriving at /hooks/<route>
  - poll: any HTTP endpoint at an interval

A trigger has a chain:
  source -> predicate (LLM yes/no) -> action (skill, prompt, send_message)

When the predicate returns yes, the action runs. Visual editing later;
JSON config now.

Schema (triggers.json):
{
  "triggers": [
    {
      "id": "stripe-revenue-alert",
      "enabled": true,
      "source": {"kind": "webhook", "route": "stripe"},
      "predicate": "Did weekly revenue drop more than 10% week-over-week?",
      "action": {
        "kind": "agent",
        "prompt": "Investigate yesterday's Stripe data and draft a 3-paragraph postmortem.",
        "deliver_to": "home"
      }
    }
  ]
}
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.triggers")

TRIGGERS_FILE = Path.home() / ".opengriffin" / "triggers.json"


def _load() -> dict:
    if not TRIGGERS_FILE.is_file():
        return {"triggers": []}
    try:
        return json.loads(TRIGGERS_FILE.read_text())
    except Exception:
        return {"triggers": []}


def _save(data: dict) -> None:
    TRIGGERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRIGGERS_FILE.write_text(json.dumps(data, indent=2) + "\n")


# ----------------------------- evaluation -----------------------------


async def evaluate(trigger: dict, event_payload: dict | None = None) -> str | None:
    """Evaluate a trigger against an inbound event. Returns the agent's response,
    or None if the predicate did not fire.

    Predicate is evaluated by Claude with a strict yes/no contract.
    """
    from . import bot as bot_module  # noqa

    predicate = trigger.get("predicate", "").strip()
    if not predicate:
        # No predicate → fire unconditionally
        decision = "yes"
    else:
        # Ask Claude. Tight prompt.
        ctx = json.dumps(event_payload or {}, indent=2)[:2000]
        ask = (
            f"You are evaluating a trigger condition. Reply with EXACTLY 'yes' "
            f"or 'no', followed by a one-sentence reason. No other text.\n\n"
            f"Condition: {predicate}\n\n"
            f"Event payload:\n{ctx}\n"
        )
        try:
            reply = await bot_module.ask_claude_with_progress(0, ask, None, status_msg_id=None)
        except Exception as e:
            log.warning("predicate eval failed: %s", e)
            return None
        decision = (reply or "no").strip().lower()[:3]

    if not decision.startswith("yes"):
        return None

    # Execute the action
    action = trigger.get("action") or {}
    kind = action.get("kind", "agent")
    if kind == "agent":
        prompt = action.get("prompt", "")
        if event_payload:
            prompt += "\n\nEvent payload:\n" + json.dumps(event_payload, indent=2)[:2000]
        try:
            return await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
        except Exception as e:
            log.exception("trigger action failed")
            return f"action failed: {e}"
    elif kind == "send":
        # Just send a message via the configured bot
        from botctx import CTX

        chat = action.get("deliver_to") or CTX.home_chat_id
        text = action.get("text", "trigger fired")
        if CTX.bot and chat:
            await CTX.bot.send_message(chat_id=chat, text=text)
        return "sent"
    else:
        log.warning("unknown action kind: %s", kind)
    return None


# ----------------------------- registration -----------------------------


def install_into_scheduler(scheduler) -> int:
    """For every trigger with source.kind == 'cron' or 'poll', register a job."""
    n = 0
    for t in _load().get("triggers", []):
        if not t.get("enabled", True):
            continue
        src = t.get("source") or {}
        if src.get("kind") == "cron":
            from apscheduler.triggers.cron import CronTrigger

            scheduler.add_job(
                _run_trigger,
                trigger=CronTrigger.from_crontab(src["expr"]),
                args=[t],
                id=f"trigger:{t['id']}",
                name=f"trigger:{t['id']}",
                replace_existing=True,
            )
            n += 1
        elif src.get("kind") == "poll":
            from apscheduler.triggers.interval import IntervalTrigger

            scheduler.add_job(
                _run_poll_trigger,
                trigger=IntervalTrigger(seconds=int(src.get("interval_sec", 300))),
                args=[t],
                id=f"trigger:{t['id']}",
                name=f"trigger:{t['id']}",
                replace_existing=True,
            )
            n += 1
    return n


async def _run_trigger(trigger: dict) -> None:
    log.info("Trigger %s firing (cron)", trigger.get("id"))
    await evaluate(
        trigger, event_payload={"fired_at": dt.datetime.now().isoformat(), "kind": "cron"}
    )


async def _run_poll_trigger(trigger: dict) -> None:
    """For poll triggers: fetch the URL, pass payload to predicate."""
    import aiohttp

    src = trigger.get("source") or {}
    url = src.get("url")
    if not url:
        return
    try:
        async with aiohttp.ClientSession() as sess, sess.get(url, timeout=15) as resp:
            payload = await resp.text()
            try:
                payload_obj = json.loads(payload)
            except Exception:
                payload_obj = {"text": payload[:2000]}
    except Exception as e:
        log.warning("poll fetch failed: %s", e)
        return
    await evaluate(trigger, event_payload={"kind": "poll", "url": url, "data": payload_obj})


async def webhook_dispatch(route: str, payload: dict) -> list[str]:
    """Called by the webhook handler when an event arrives. Fires all
    triggers whose source.kind == 'webhook' and source.route matches.
    """
    fired = []
    for t in _load().get("triggers", []):
        if not t.get("enabled", True):
            continue
        src = t.get("source") or {}
        if src.get("kind") == "webhook" and src.get("route") == route:
            result = await evaluate(t, event_payload=payload)
            if result:
                fired.append(t["id"])
    return fired


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "trigger_create",
    "Create an ambient trigger that fires from cron, webhook, or poll. The agent uses this when the user describes a 'when X happens, do Y' workflow. Source kinds: cron (with expr), webhook (with route), poll (with url + interval_sec).",
    {
        "id": Annotated[str, "Unique trigger id (kebab-case)"],
        "source_kind": Annotated[str, "cron | webhook | poll"],
        "source_config": Annotated[
            str,
            "JSON config for the source. cron: {expr: '0 9 * * *'}. webhook: {route: 'stripe'}. poll: {url: '...', interval_sec: 300}",
        ],
        "predicate": Annotated[
            str | None, "Optional yes/no question evaluated by Claude before action fires"
        ],
        "action_kind": Annotated[str, "agent | send"],
        "action_prompt": Annotated[str | None, "Prompt text for action_kind=agent"],
        "deliver_to": Annotated[str | None, "Chat id to deliver result; 'home' for default"],
    },
)
async def _create(args: dict) -> dict:
    try:
        source_cfg = json.loads(args.get("source_config") or "{}")
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"source_config invalid JSON: {e}"}],
            "is_error": True,
        }
    trigger = {
        "id": args["id"],
        "enabled": True,
        "source": {"kind": args["source_kind"], **source_cfg},
        "predicate": args.get("predicate", ""),
        "action": {
            "kind": args["action_kind"],
            "prompt": args.get("action_prompt", ""),
            "deliver_to": args.get("deliver_to", "home"),
        },
    }
    data = _load()
    data["triggers"] = [t for t in data["triggers"] if t["id"] != args["id"]]
    data["triggers"].append(trigger)
    _save(data)
    return {
        "content": [
            {"type": "text", "text": f"created trigger {args['id']} (restart bot to register)"}
        ]
    }


@tool(
    "trigger_list",
    "List all configured ambient triggers.",
    {},
)
async def _list(args: dict) -> dict:
    items = _load().get("triggers", [])
    if not items:
        return {"content": [{"type": "text", "text": "(no triggers)"}]}
    lines = []
    for t in items:
        src = t.get("source", {})
        on_off = "✓" if t.get("enabled", True) else "✗"
        lines.append(
            f"{on_off} {t['id']} — {src.get('kind')}({src.get('expr') or src.get('route') or src.get('url')})"
        )
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "trigger_remove",
    "Delete an ambient trigger by id.",
    {"id": Annotated[str, "Trigger id"]},
)
async def _remove(args: dict) -> dict:
    data = _load()
    before = len(data["triggers"])
    data["triggers"] = [t for t in data["triggers"] if t["id"] != args["id"]]
    if before == len(data["triggers"]):
        return {
            "content": [{"type": "text", "text": f"no such trigger: {args['id']}"}],
            "is_error": True,
        }
    _save(data)
    return {"content": [{"type": "text", "text": f"removed {args['id']}"}]}


TRIGGERS_SERVER = create_sdk_mcp_server(
    name="triggers",
    version="1.0.0",
    tools=[_create, _list, _remove],
)
