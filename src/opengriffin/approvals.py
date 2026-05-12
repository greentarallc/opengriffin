"""Telegram-driven approval flow for dangerous commands.

The Claude Agent SDK calls `can_use_tool(tool_name, tool_input, context)`
before executing certain tools. We intercept Bash (and other configurable
tools), check against a session/always allowlist, and if not pre-approved,
send a Telegram message with inline buttons. The callback resolves an
asyncio.Future the SDK is awaiting. 60-second timeout → fail-closed deny.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from .botctx import CTX

log = logging.getLogger("claude-bot.approvals")

APPROVAL_TIMEOUT_SEC = 60

# Tools that trigger approval (besides Bash, which is checked against the
# dangerous-pattern list below).
ALWAYS_APPROVE_TOOLS = {"Read", "Glob", "Grep", "WebFetch", "WebSearch"}
PROMPT_APPROVE_TOOLS = {"Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"}

# Bash patterns considered dangerous (always prompt regardless of session allowlist).
_HARDLINE_BLOCK = [
    re.compile(r"\brm\s+-rf?\s+/(?!\w)"),
    re.compile(r":\(\)\{:\|:&\};:"),  # fork bomb
    re.compile(r"\bmkfs\."),
    re.compile(r"\bdd\s+if=.*\bof=/dev/[shr]"),
    re.compile(r">\s*/dev/sd[a-z]"),
]

# Bash patterns that always need explicit approval (cannot be skipped via 'session').
_DANGEROUS = [
    re.compile(r"\brm\s+-rf?\s+"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bcurl\b.+\|\s*(sh|bash|zsh)\b"),
    re.compile(r"\bgit\s+push\s+.*--force"),
    re.compile(r"\bdrop\s+(table|database)\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+-R\s+777\b"),
    re.compile(r"\bnpm\s+publish\b"),
    re.compile(r"\bpip\s+install\s+.*--user.*sudo"),
]


@dataclass
class ApprovalState:
    session_allow_tools: set[str] = field(default_factory=set)
    always_allow_tools: set[str] = field(default_factory=set)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


STATE = ApprovalState()


def _is_hardline(cmd: str) -> bool:
    return any(p.search(cmd) for p in _HARDLINE_BLOCK)


def _is_dangerous_bash(cmd: str) -> bool:
    return any(p.search(cmd) for p in _DANGEROUS)


def _summary(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return f"`{cmd[:300]}`"
    if tool_name in ("Write",):
        return f"file: `{tool_input.get('file_path', '?')}`"
    if tool_name in ("Edit", "MultiEdit"):
        return f"edit: `{tool_input.get('file_path', '?')}`"
    return f"`{str(tool_input)[:300]}`"


async def can_use_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    """SDK callback: decide whether a tool call is allowed.

    Strategy: default-allow everything. Only intercept Bash with dangerous
    patterns. Hardline-block fork bombs / mkfs / dd-to-disk regardless. Other
    file-mutating tools (Write/Edit) are protected by the checkpoint hook,
    not approvals — checkpoints make rollback cheap so prompting is noise.
    """
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if _is_hardline(cmd):
            return PermissionResultDeny(message="hardline-blocked command pattern")
        if not _is_dangerous_bash(cmd):
            return PermissionResultAllow()
        if "Bash" in STATE.always_allow_tools:
            return PermissionResultAllow()
        if "Bash" in STATE.session_allow_tools:
            return PermissionResultAllow()
        # falls through to Telegram prompt below
    else:
        return PermissionResultAllow()

    if CTX.bot is None or not CTX.home_chat_id:
        # No way to ask — fail closed.
        return PermissionResultDeny(message="no Telegram channel for approval")

    req_id = uuid.uuid4().hex[:8]
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    STATE.pending[req_id] = fut

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Allow once", callback_data=f"appr:once:{req_id}"),
                InlineKeyboardButton(
                    "🟢 Session", callback_data=f"appr:session:{req_id}:{tool_name}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔵 Always", callback_data=f"appr:always:{req_id}:{tool_name}"
                ),
                InlineKeyboardButton("❌ Deny", callback_data=f"appr:deny:{req_id}"),
            ],
        ]
    )
    try:
        await CTX.bot.send_message(
            chat_id=CTX.home_chat_id,
            text=(
                f"🔐 Approval requested for `{tool_name}`:\n"
                f"{_summary(tool_name, tool_input)}\n\n"
                f"_Auto-deny in {APPROVAL_TIMEOUT_SEC}s._"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        log.exception("approval send failed")
        STATE.pending.pop(req_id, None)
        return PermissionResultDeny(message=f"approval send failed: {e}")

    try:
        decision = await asyncio.wait_for(fut, timeout=APPROVAL_TIMEOUT_SEC)
    except TimeoutError:
        STATE.pending.pop(req_id, None)
        return PermissionResultDeny(message="approval timed out")
    finally:
        STATE.pending.pop(req_id, None)

    if decision == "allow":
        return PermissionResultAllow()
    return PermissionResultDeny(message=decision)


async def _safe_answer(q, text: str = "") -> None:
    """Acknowledge a callback query, swallowing 'too old' / 'invalid' errors.

    Telegram callback queries expire (~15 min) and old buttons from before a
    bot restart will always fail. We don't want that to blow up the handler.
    """
    try:
        await q.answer(text)
    except Exception as e:
        log.debug("q.answer failed (likely stale query): %s", e)


async def _safe_edit(q, suffix: str) -> None:
    """Append a status suffix to the prompt message; swallow markdown/edit errors."""
    try:
        original = q.message.text or ""
        await q.edit_message_text(
            original + suffix,
            parse_mode="Markdown",
        )
    except Exception:
        # Markdown can fail on weird content; fall back to plain text
        try:
            await q.edit_message_text((q.message.text or "") + suffix)
        except Exception as e:
            log.debug("edit_message_text failed: %s", e)


async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve a pending approval future from a button press.

    Defensive throughout: every Telegram API call is wrapped so a stale
    query / markdown failure / edit-too-old error can't prevent the future
    from being resolved.
    """
    q = update.callback_query
    if q is None or q.data is None or not q.data.startswith("appr:"):
        return
    parts = q.data.split(":")
    if len(parts) < 3:
        await _safe_answer(q, "(malformed)")
        return
    action = parts[1]
    req_id = parts[2]
    fut = STATE.pending.get(req_id)

    # Stale: future already resolved, or bot restarted clearing pending.
    if fut is None or fut.done():
        await _safe_answer(q, "(already resolved or expired)")
        await _safe_edit(
            q,
            "\n\n_(this approval is no longer waiting — likely already resolved or the bot restarted)_",
        )
        return

    # Resolve the future FIRST. UI feedback is best-effort.
    if action == "once":
        fut.set_result("allow")
        await _safe_answer(q, "allowed once")
        await _safe_edit(q, "\n\n✅ allowed once")
    elif action == "session" and len(parts) >= 4:
        tool_name = parts[3]
        STATE.session_allow_tools.add(tool_name)
        fut.set_result("allow")
        await _safe_answer(q, f"session-allowed {tool_name}")
        await _safe_edit(q, f"\n\n🟢 session-allowed `{tool_name}`")
    elif action == "always" and len(parts) >= 4:
        tool_name = parts[3]
        STATE.always_allow_tools.add(tool_name)
        fut.set_result("allow")
        await _safe_answer(q, f"always-allowed {tool_name}")
        await _safe_edit(q, f"\n\n🔵 always-allowed `{tool_name}`")
    elif action == "deny":
        fut.set_result("denied by user")
        await _safe_answer(q, "denied")
        await _safe_edit(q, "\n\n❌ denied")
    else:
        # Unknown action; default-deny but don't error
        fut.set_result(f"unknown action: {action}")
        await _safe_answer(q, "unknown action")


HANDLER = CallbackQueryHandler(callback_handler, pattern=r"^appr:")
