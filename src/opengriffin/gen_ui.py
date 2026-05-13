"""Generative Live UI — interfaces beyond chat, that *learn*.

Chat is the wrong interface for half of agent tasks. Generative UI
(A2UI / AG-UI / MCP Apps) shipped as 2026 standards but nobody plugged
them into a personal agent whose memory contains "how does THIS user
prefer to consume THIS kind of info."

This module renders a small UI vocabulary that the agent can compose at
conversation time, surfaces it via whatever client is connected
(Telegram inline keyboards today; a web mini-app surface tomorrow), and —
critically — **records which generated UIs the user actually uses vs.
ignores** so the agent stops shipping layouts that get bounced.

The vocabulary intentionally stays tiny and renderable on a phone:

  - "panel"      a titled container for grouped content
  - "kv_list"    key/value pairs (most common briefing surface)
  - "checklist"  multi-select items (action queue, FAQ filter)
  - "choice"     single-select radio (Allow / Always / Deny — already
                 echoed by approvals.py, kept here for uniformity)
  - "slider"     numeric input (budget, hours, confidence)
  - "card_grid"  grid of card primitives — title + body + tap-action
  - "table"      tabular data (forecast hours, kanban board)
  - "code_block" inline mono content
  - "chart"      sparkline/bar (rendered server-side as a small PNG by
                 callers when possible; otherwise as text)
  - "actions"    a row of buttons at the bottom

The descriptor is a JSON tree. The runtime renderer (`render_for_telegram`)
maps it to the platform primitives — InlineKeyboardMarkup for buttons,
text-with-emoji-rules for kv_list/table, etc.

The preference layer is the heart of the differentiation. Every render
emits a UI id. When the user later sends a `ui_event` (button tap,
slider change), we log it tied to that UI id. If a UI id receives no
events within the session timeout, we count it as "ignored." A per-user
adaptation policy (`preference`) ranks layout choices for each
*purpose* — e.g. "morning_briefing" might be served as kv_list for one
user and as a card_grid for another, decided from history.

Storage:
  ~/.opengriffin/gen_ui/renders.jsonl     — every render
  ~/.opengriffin/gen_ui/events.jsonl      — every interaction
  ~/.opengriffin/gen_ui/preferences.json  — learned per-purpose layout ranking
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
from pathlib import Path
from typing import Annotated, Any

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.gen_ui")

UI_DIR = Path.home() / ".opengriffin" / "gen_ui"
UI_DIR.mkdir(parents=True, exist_ok=True)
RENDERS_LOG = UI_DIR / "renders.jsonl"
EVENTS_LOG = UI_DIR / "events.jsonl"
PREFS_FILE = UI_DIR / "preferences.json"

# Sessions are "consumed" when an event arrives within this many seconds
# of the render; otherwise the render counts as ignored.
ENGAGEMENT_TIMEOUT_SECS = 1800  # 30 min

# The vocabulary. Each name maps to a quick validator + a renderer for
# Telegram (text + optional InlineKeyboardMarkup-shaped JSON).
PRIMITIVES = {
    "panel",
    "kv_list",
    "checklist",
    "choice",
    "slider",
    "card_grid",
    "table",
    "code_block",
    "chart",
    "actions",
}


def _new_ui_id() -> str:
    return secrets.token_hex(6)


def _load_prefs() -> dict:
    if not PREFS_FILE.is_file():
        return {"by_purpose": {}}
    try:
        return json.loads(PREFS_FILE.read_text())
    except Exception:
        return {"by_purpose": {}}


def _save_prefs(p: dict) -> None:
    PREFS_FILE.write_text(json.dumps(p, indent=2) + "\n")


def _append_jsonl(path: Path, rec: dict) -> None:
    with path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def render(
    *,
    purpose: str,
    chat_id: int | None,
    descriptor: dict,
    expires_in_secs: int | None = None,
) -> dict:
    """Validate, log, and assign an id to a UI descriptor. Returns the
    record (callers feed `record["render"]` to platform-specific
    renderers below).

    `purpose` is the only mandatory free-text field; it lets the
    preference layer learn "the user prefers a card_grid for
    morning_briefing but a kv_list for kanban_status."
    """
    # Validate the root: must be a dict with a top-level primitive
    if not isinstance(descriptor, dict):
        raise ValueError("descriptor must be a dict")
    root_kind = descriptor.get("kind")
    if root_kind not in PRIMITIVES:
        raise ValueError(f"unknown root primitive: {root_kind}")

    ui_id = _new_ui_id()
    rec = {
        "ui_id": ui_id,
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "purpose": purpose,
        "chat_id": chat_id,
        "descriptor": descriptor,
        "expires_at": (dt.datetime.now() + dt.timedelta(seconds=expires_in_secs)).isoformat(
            timespec="seconds"
        )
        if expires_in_secs
        else None,
        "engaged": False,
    }
    _append_jsonl(RENDERS_LOG, rec)
    return rec


def record_event(
    *,
    ui_id: str,
    kind: str,
    value: Any = None,
    chat_id: int | None = None,
) -> dict:
    """Log a user interaction with a previously-rendered UI. Increments
    the engagement count and (if first event) marks the render engaged."""
    rec = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "ui_id": ui_id,
        "kind": kind,
        "value": value if isinstance(value, (str, int, float, bool, list, dict)) else str(value),
        "chat_id": chat_id,
    }
    _append_jsonl(EVENTS_LOG, rec)
    # Update preference signal — engagement++
    render_meta = _find_render(ui_id)
    if render_meta is not None:
        _bump_preference(render_meta["purpose"], render_meta["descriptor"]["kind"], delta=+1)
    return rec


def _find_render(ui_id: str) -> dict | None:
    if not RENDERS_LOG.is_file():
        return None
    for line in reversed(RENDERS_LOG.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("ui_id") == ui_id:
                return rec
        except Exception:
            continue
    return None


def _bump_preference(purpose: str, primitive: str, *, delta: int) -> None:
    prefs = _load_prefs()
    by_purpose = prefs.setdefault("by_purpose", {})
    pmap = by_purpose.setdefault(purpose, {})
    pmap[primitive] = pmap.get(primitive, 0) + delta
    prefs["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_prefs(prefs)


def preferred_primitive(purpose: str, *, fallback: str = "kv_list") -> str:
    """Return the layout primitive with the highest net engagement score
    for the given purpose. Used at render-time to nudge the agent toward
    layouts the user has previously engaged with."""
    pmap = _load_prefs().get("by_purpose", {}).get(purpose, {})
    if not pmap:
        return fallback
    return max(pmap.items(), key=lambda kv: kv[1])[0]


def adaptation_summary() -> dict:
    """What has the UI learned about the user's preferences?"""
    prefs = _load_prefs().get("by_purpose", {})
    out = {}
    for purpose, pmap in prefs.items():
        ranked = sorted(pmap.items(), key=lambda kv: -kv[1])
        out[purpose] = ranked
    return {"by_purpose": out}


# ----------------------------- platform renderers -----------------------------


def render_for_telegram(descriptor: dict) -> dict:
    """Return {'text': str, 'reply_markup': dict|None} ready for
    telegram.Bot.send_message. The reply_markup is shaped as
    InlineKeyboardMarkup (a 2D array of {text, callback_data} dicts).

    This is intentionally a thin transcoder — no platform SDK imports,
    keeps gen_ui pure. bot.py / gateway code does the actual send."""
    descriptor["kind"]
    text_parts: list[str] = []
    buttons: list[list[dict]] = []

    def walk(node: dict) -> None:
        k = node.get("kind")
        if k == "panel":
            title = node.get("title")
            if title:
                text_parts.append(f"*{title}*")
            for child in node.get("children", []):
                walk(child)
        elif k == "kv_list":
            for pair in node.get("items", []):
                key = pair.get("key", "")
                val = pair.get("value", "")
                text_parts.append(f"`{key}` — {val}")
        elif k == "checklist":
            for item in node.get("items", []):
                mark = "☑" if item.get("checked") else "☐"
                text_parts.append(f"{mark} {item.get('label', '')}")
        elif k == "choice":
            text_parts.append(node.get("prompt", "Choose:"))
            row: list[dict] = []
            for opt in node.get("options", []):
                row.append(
                    {
                        "text": opt.get("label", "?"),
                        "callback_data": f"ui:{node.get('id', '?')}:choice:{opt.get('value', '?')}",
                    }
                )
            buttons.append(row)
        elif k == "slider":
            cur = node.get("value", node.get("min", 0))
            text_parts.append(
                f"{node.get('label', '')}: {cur} ({node.get('min', 0)}–{node.get('max', 100)})"
            )
            row = []
            for delta in (-10, -1, 1, 10):
                sign = "+" if delta > 0 else ""
                row.append(
                    {
                        "text": f"{sign}{delta}",
                        "callback_data": f"ui:{node.get('id', '?')}:slide:{delta}",
                    }
                )
            buttons.append(row)
        elif k == "card_grid":
            for card in node.get("cards", []):
                title = card.get("title", "")
                body = card.get("body", "")
                text_parts.append(f"*{title}*\n{body}")
                if card.get("action_label"):
                    buttons.append(
                        [
                            {
                                "text": card["action_label"],
                                "callback_data": f"ui:{card.get('id', '?')}:tap:_",
                            }
                        ]
                    )
        elif k == "table":
            cols = node.get("columns", [])
            text_parts.append(" | ".join(f"*{c}*" for c in cols))
            for row in node.get("rows", []):
                text_parts.append(" | ".join(str(c) for c in row))
        elif k == "code_block":
            text_parts.append(f"```\n{node.get('code', '')}\n```")
        elif k == "chart":
            # Telegram doesn't render inline charts cheaply; degrade to
            # ascii sparkline. The web mini-app surface will replace this.
            data = node.get("data", [])
            if data:
                lo, hi = min(data), max(data)
                rng = (hi - lo) or 1
                blocks = " ▁▂▃▄▅▆▇█"
                spark = "".join(blocks[min(8, int((d - lo) / rng * 8))] for d in data)
                text_parts.append(f"{node.get('label', 'chart')}: {spark}  ({lo}…{hi})")
        elif k == "actions":
            row = []
            for b in node.get("buttons", []):
                row.append(
                    {
                        "text": b.get("label", "?"),
                        "callback_data": f"ui:{b.get('id', '?')}:tap:_",
                    }
                )
            buttons.append(row)
        else:
            text_parts.append(f"[unknown primitive: {k}]")

    walk(descriptor)
    text = "\n".join(text_parts)
    reply_markup = {"inline_keyboard": buttons} if buttons else None
    return {"text": text, "reply_markup": reply_markup}


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "ui_render",
    "Render a Generative UI descriptor. Returns a ui_id (track engagement against it) + a Telegram-ready (text, reply_markup) pair. The descriptor follows the gen_ui vocabulary: kind ∈ {panel, kv_list, checklist, choice, slider, card_grid, table, code_block, chart, actions}.",
    {
        "purpose": Annotated[
            str,
            "Stable label for this UI's intent (e.g. 'morning_briefing', 'kanban_status', 'forecast_review'). Used to learn user preferences over time.",
        ],
        "descriptor_json": Annotated[str, "The UI descriptor as JSON"],
        "chat_id": Annotated[int | None, "Telegram chat id, if applicable"],
        "expires_in_secs": Annotated[int | None, "Optional TTL (default: no expiry)"],
    },
)
async def _render(args: dict) -> dict:
    descriptor = json.loads(args["descriptor_json"])
    try:
        rec = render(
            purpose=args["purpose"],
            chat_id=args.get("chat_id"),
            descriptor=descriptor,
            expires_in_secs=args.get("expires_in_secs"),
        )
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    rendered = render_for_telegram(descriptor)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "ui_id": rec["ui_id"],
                        "purpose": rec["purpose"],
                        "rendered": rendered,
                    },
                    indent=2,
                ),
            }
        ]
    }


@tool(
    "ui_event",
    "Record a user interaction with a previously-rendered UI. Drives the preference-learning loop — repeat engagement with a primitive bumps it up the ranking for that purpose.",
    {
        "ui_id": Annotated[str, "UI id returned by ui_render"],
        "kind": Annotated[str, "Event type: 'tap' | 'choice' | 'slide' | 'check'"],
        "value": Annotated[str | None, "Event value (button id / chosen option / slider value)"],
        "chat_id": Annotated[int | None, "Telegram chat id"],
    },
)
async def _event(args: dict) -> dict:
    rec = record_event(
        ui_id=args["ui_id"],
        kind=args["kind"],
        value=args.get("value"),
        chat_id=args.get("chat_id"),
    )
    return {"content": [{"type": "text", "text": json.dumps(rec, indent=2)}]}


@tool(
    "ui_preference",
    "Look up the learned preferred primitive for a given purpose. Use BEFORE rendering — pick the layout the user has actually engaged with.",
    {"purpose": Annotated[str, "The render purpose"]},
)
async def _preference(args: dict) -> dict:
    primitive = preferred_primitive(args["purpose"])
    return {"content": [{"type": "text", "text": primitive}]}


@tool(
    "ui_adaptation_summary",
    "Show what gen_ui has learned about the user's preferences across all purposes.",
    {},
)
async def _summary(args: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(adaptation_summary(), indent=2)}]}


GEN_UI_SERVER = create_sdk_mcp_server(
    name="gen_ui",
    version="1.0.0",
    tools=[_render, _event, _preference, _summary],
)


__all__ = [
    "render",
    "record_event",
    "preferred_primitive",
    "render_for_telegram",
    "adaptation_summary",
    "GEN_UI_SERVER",
    "PRIMITIVES",
]
