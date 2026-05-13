"""Cross-platform identity — one user across Telegram + Discord + Slack + Email + iMessage.

A single human's per-platform user IDs are linked to one OpenGriffin account.
Memory, kanban, sessions, and SOUL are scoped to the account, not to a
platform-specific id.

Storage: identity.json
{
  "accounts": {
    "alice": {
      "platforms": {
        "telegram": "YOUR_TELEGRAM_CHAT_ID",
        "discord":  "YOUR_DISCORD_USER_ID",
        "email":    "alice@example.com"
      },
      "created_at": "...",
      "soul_path": "memories/SOUL.md"
    }
  }
}

To prove ownership: user issues a one-time link code in account A; sends it
from account B. Server matches and links.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

IDENTITY_FILE = Path.home() / ".opengriffin" / "identity.json"
IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)

# In-memory pending link codes (short TTL)
_PENDING_LINKS: dict[str, dict] = {}  # code → {account, expires}


def _load() -> dict:
    if not IDENTITY_FILE.is_file():
        return {"accounts": {}}
    try:
        return json.loads(IDENTITY_FILE.read_text())
    except Exception:
        return {"accounts": {}}


def _save(data: dict) -> None:
    IDENTITY_FILE.write_text(json.dumps(data, indent=2) + "\n")


def create_account(handle: str) -> dict:
    data = _load()
    if handle in data["accounts"]:
        return data["accounts"][handle]
    data["accounts"][handle] = {
        "handle": handle,
        "platforms": {},
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)
    return data["accounts"][handle]


def link_platform(handle: str, platform: str, platform_id: str) -> bool:
    data = _load()
    if handle not in data["accounts"]:
        return False
    data["accounts"][handle].setdefault("platforms", {})[platform] = platform_id
    _save(data)
    return True


def lookup_account(platform: str, platform_id: str) -> str | None:
    data = _load()
    for handle, acc in data["accounts"].items():
        if acc.get("platforms", {}).get(platform) == str(platform_id):
            return handle
    return None


def list_accounts() -> list[dict]:
    return list(_load().get("accounts", {}).values())


def issue_link_code(handle: str, ttl_seconds: int = 600) -> str:
    """Issue a one-time code. Send this from another platform to link it."""
    code = secrets.token_hex(4).upper()
    _PENDING_LINKS[code] = {
        "handle": handle,
        "expires": dt.datetime.now() + dt.timedelta(seconds=ttl_seconds),
    }
    return code


def consume_link_code(code: str, platform: str, platform_id: str) -> str | None:
    """Called when a code arrives via a different platform. Returns handle if linked."""
    entry = _PENDING_LINKS.pop(code.upper(), None)
    if entry is None:
        return None
    if entry["expires"] < dt.datetime.now():
        return None
    handle = entry["handle"]
    link_platform(handle, platform, platform_id)
    return handle


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "identity_create",
    "Create an OpenGriffin account that will be the home for cross-platform memory linking.",
    {"handle": Annotated[str, "Public handle (e.g. 'alice')"]},
)
async def _create(args: dict) -> dict:
    acc = create_account(args["handle"])
    return {"content": [{"type": "text", "text": json.dumps(acc, indent=2)}]}


@tool(
    "identity_link_code",
    "Issue a 6-char link code (10 min TTL). User sends this code from a NEW platform to link it.",
    {"handle": Annotated[str, "Account handle"]},
)
async def _link_code(args: dict) -> dict:
    code = issue_link_code(args["handle"])
    return {
        "content": [
            {
                "type": "text",
                "text": f"Link code: *{code}*\nValid 10 min. Send it from the platform you want to link.",
            }
        ]
    }


@tool(
    "identity_link_consume",
    "Server-side: consume a link code arriving from a new platform.",
    {
        "code": Annotated[str, "Link code"],
        "platform": Annotated[str, "Platform name"],
        "platform_id": Annotated[str, "User id on that platform"],
    },
)
async def _consume(args: dict) -> dict:
    handle = consume_link_code(args["code"], args["platform"], args["platform_id"])
    if handle is None:
        return {"content": [{"type": "text", "text": "invalid or expired code"}], "is_error": True}
    return {"content": [{"type": "text", "text": f"linked to {handle}"}]}


@tool(
    "identity_list",
    "Show all linked accounts and their platforms.",
    {},
)
async def _list(args: dict) -> dict:
    accounts = list_accounts()
    if not accounts:
        return {"content": [{"type": "text", "text": "(no accounts)"}]}
    lines = []
    for a in accounts:
        plats = ", ".join(f"{k}={v}" for k, v in a.get("platforms", {}).items()) or "(none)"
        lines.append(f"{a['handle']} — {plats}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


IDENTITY_SERVER = create_sdk_mcp_server(
    name="identity",
    version="1.0.0",
    tools=[_create, _link_code, _consume, _list],
)
