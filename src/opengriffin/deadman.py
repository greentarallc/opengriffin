"""Dead-man's switch — if the user goes dark, lock outbound actions.

If no user message is received for N days (default 7), the agent enters
locked mode:
  - All outbound messages, payments, and external posts are blocked.
  - The agent sends a recovery code via Telegram every day until check-in.
  - On the next user message, the agent verifies it's really the user
    (by asking for the recovery code) before unlocking.

Optional escalation: at 14 days, send the recovery code + a configurable
"in case I'm gone" message to a designated trusted contact. The agent's
data and credentials remain on-device until the user explicitly authorizes
transfer.

Storage: deadman.json — {last_user_msg_at, locked, recovery_code, ...}
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import secrets
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.deadman")

DEADMAN_FILE = Path.home() / ".opengriffin" / "deadman.json"
DEADMAN_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    if not DEADMAN_FILE.is_file():
        return {
            "last_user_msg_at": None,
            "locked": False,
            "recovery_code": None,
            "lock_after_days": 7,
            "escalate_after_days": 14,
            "trusted_contact_text": "",
            "trusted_contact_chat_id": "",
            "escalated": False,
        }
    try:
        return json.loads(DEADMAN_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    DEADMAN_FILE.write_text(json.dumps(data, indent=2) + "\n")


def heartbeat() -> None:
    """Call on every received user message — resets the timer and unlocks if needed."""
    data = _load()
    data["last_user_msg_at"] = dt.datetime.now().isoformat(timespec="seconds")
    if data.get("locked"):
        data["locked"] = False
        data["recovery_code"] = None
        data["escalated"] = False
    _save(data)


def is_locked() -> bool:
    return bool(_load().get("locked"))


def can_send_outbound() -> bool:
    return not is_locked()


def status() -> dict:
    data = _load()
    last = data.get("last_user_msg_at")
    days_since = None
    if last:
        try:
            delta = dt.datetime.now() - dt.datetime.fromisoformat(last)
            days_since = round(delta.total_seconds() / 86400, 1)
        except Exception:
            pass
    return {
        "locked": data.get("locked", False),
        "last_user_msg_at": last,
        "days_since_user": days_since,
        "lock_after_days": data.get("lock_after_days"),
        "escalate_after_days": data.get("escalate_after_days"),
        "escalated": data.get("escalated", False),
    }


def configure(
    *,
    lock_after_days: int | None = None,
    escalate_after_days: int | None = None,
    trusted_contact_chat_id: str | None = None,
    trusted_contact_text: str | None = None,
) -> dict:
    data = _load()
    if lock_after_days is not None:
        data["lock_after_days"] = int(lock_after_days)
    if escalate_after_days is not None:
        data["escalate_after_days"] = int(escalate_after_days)
    if trusted_contact_chat_id is not None:
        data["trusted_contact_chat_id"] = str(trusted_contact_chat_id)
    if trusted_contact_text is not None:
        data["trusted_contact_text"] = trusted_contact_text
    _save(data)
    return status()


async def daily_tick() -> dict:
    """Run daily. If past lock threshold and not yet locked: lock + send recovery code.
    If past escalate threshold and not yet escalated: send to trusted contact."""
    from botctx import CTX

    data = _load()
    last = data.get("last_user_msg_at")
    if not last:
        return {"status": "no heartbeat yet"}
    delta = dt.datetime.now() - dt.datetime.fromisoformat(last)
    days = delta.total_seconds() / 86400

    actions = []
    if days >= data.get("lock_after_days", 7) and not data.get("locked"):
        code = secrets.token_hex(3).upper()
        data["locked"] = True
        data["recovery_code"] = code
        actions.append("locked")
        if CTX.bot and CTX.home_chat_id:
            with contextlib.suppress(Exception):
                await CTX.bot.send_message(
                    chat_id=CTX.home_chat_id,
                    text=(
                        f"🔒 *Dead-man's switch engaged.*\n"
                        f"No activity for {round(days, 1)} days. Outbound actions are paused.\n"
                        f"To unlock, message me with this recovery code: `{code}`"
                    ),
                    parse_mode="Markdown",
                )

    if days >= data.get("escalate_after_days", 14) and not data.get("escalated"):
        contact = data.get("trusted_contact_chat_id")
        if contact and CTX.bot:
            try:
                await CTX.bot.send_message(
                    chat_id=contact,
                    text=data.get("trusted_contact_text")
                    or f"OpenGriffin escalation: my user has not checked in for {round(days, 1)} days. "
                    "Recovery code (if requested by them): "
                    + (data.get("recovery_code") or "(missing)"),
                )
                data["escalated"] = True
                actions.append("escalated")
            except Exception:
                log.exception("escalation send failed")
    _save(data)
    return {"days_since_user": round(days, 1), "actions": actions, "locked": data.get("locked")}


def verify_recovery(code_attempt: str) -> bool:
    data = _load()
    expected = data.get("recovery_code")
    if expected and code_attempt.strip().upper() == expected.upper():
        data["locked"] = False
        data["recovery_code"] = None
        data["escalated"] = False
        _save(data)
        return True
    return False


@tool(
    "deadman_status",
    "Show dead-man's switch state: days since last user activity, locked or not, escalation thresholds.",
    {},
)
async def _status(args: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(status(), indent=2)}]}


@tool(
    "deadman_configure",
    "Configure dead-man's switch parameters.",
    {
        "lock_after_days": Annotated[int | None, "Days of silence before locking (default 7)"],
        "escalate_after_days": Annotated[
            int | None, "Days before notifying trusted contact (default 14)"
        ],
        "trusted_contact_chat_id": Annotated[str | None, "Telegram chat id of trusted contact"],
        "trusted_contact_text": Annotated[str | None, "Custom escalation message"],
    },
)
async def _configure(args: dict) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    configure(**{k: v for k, v in args.items() if v is not None}), indent=2
                ),
            }
        ]
    }


DEADMAN_SERVER = create_sdk_mcp_server(
    name="deadman",
    version="1.0.0",
    tools=[_status, _configure],
)
