"""Telegram bot powered by Claude Agent SDK.

Each Telegram chat gets persistent Claude sessions per *topic*. The SDK runs
through the local `claude` CLI, so it inherits Claude Code's stored
credentials (Claude Max OAuth) automatically — no API key needed.

User skills under ~/.claude/skills/ auto-load via `skills='all'`. Memory,
checkpoints, approvals, tools, kanban, webhooks and voice are wired in.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import aliases as aliases_module
from . import approvals as approvals_module
from . import botctx
from . import checkpoints as checkpoints_module
from . import cron as cron_module
from . import kanban as kanban_module
from . import memory as memory_module
from . import paths as paths_module
from . import progress as progress_module
from . import recall as recall_module
from . import self_improve as self_improve_module
from . import tools as tools_module
from . import topics as topics_module
from . import usage as usage_module
from . import voice as voice_module
from . import webhooks as webhooks_module
from .redact import redact

# Auto-migrate state from the legacy ~/claude-bot/ layout if present.
# Idempotent — skips anything that already exists at the new location.
paths_module.migrate_legacy_state()

# Look for .env in priority order: OG_HOME/.env (canonical), CWD (dev
# convenience for `git clone && drop .env in the repo root && opengriffin run`),
# legacy XDG location. First hit wins so there's no ambiguity about which
# file the bot is reading.
for _p in (
    paths_module.ENV_FILE,
    Path.cwd() / ".env",
    Path.home() / ".config" / "opengriffin" / ".env",
):
    if _p.is_file():
        load_dotenv(_p)
        break

# Read at startup; main() validates. Lazy so `import opengriffin.bot` works
# in tests, doctor, and other tooling without forcing a Telegram token.
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

_raw_allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
ALLOWED_USERS: set[int] = {
    int(x) for x in _raw_allowed.replace(",", " ").split() if x.strip().isdigit()
}
HOME_CHAT_ID = os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip() or (
    str(next(iter(ALLOWED_USERS))) if ALLOWED_USERS else None
)

TELEGRAM_MAX = 4000
IDLE_RESET_HOUR = 4  # daily 4am reset matches the bot default

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("opengriffin")


def build_mcp_servers() -> dict:
    servers = {
        "memory": memory_module.MEMORY_SERVER,
        "bot_tools": tools_module.BOT_TOOLS_SERVER,
        "kanban": kanban_module.KANBAN_SERVER,
        "recall": recall_module.RECALL_SERVER,
    }
    # Killer features (12)
    try:
        from . import skill_hub

        servers["skill_hub"] = skill_hub.SKILL_HUB_SERVER
    except Exception:
        pass
    try:
        from . import echo_memory

        servers["echo_memory"] = echo_memory.ECHO_SERVER
    except Exception:
        pass
    try:
        from . import triggers as _triggers

        servers["triggers"] = _triggers.TRIGGERS_SERVER
    except Exception:
        pass
    try:
        from . import pods

        servers["pods"] = pods.PODS_SERVER
    except Exception:
        pass
    try:
        from . import wallet

        servers["wallet"] = wallet.WALLET_SERVER
    except Exception:
        pass
    try:
        from . import soul_sync

        servers["soul_sync"] = soul_sync.SOUL_SYNC_SERVER
    except Exception:
        pass
    try:
        from . import routing

        servers["routing"] = routing.ROUTING_SERVER
    except Exception:
        pass
    try:
        from . import drift

        servers["drift"] = drift.DRIFT_SERVER
    except Exception:
        pass
    try:
        from . import self_healing

        servers["self_healing"] = self_healing.HEAL_SERVER
    except Exception:
        pass
    try:
        from . import skill_strategy

        servers["skill_strategy"] = skill_strategy.STRATEGY_SERVER
    except Exception:
        pass
    try:
        from . import reputation

        servers["reputation"] = reputation.REPUTATION_SERVER
    except Exception:
        pass
    # Frontier features (post-30): predictive world model + counterfactual twin,
    # inverse-safety proofs, generative UI, mesa-cognition supervisor,
    # skill leasing, personal causal layer, adversarial market.
    try:
        from . import world_model

        servers["world_model"] = world_model.WORLD_MODEL_SERVER
    except Exception:
        pass
    try:
        from . import twin

        servers["twin"] = twin.TWIN_SERVER
    except Exception:
        pass
    try:
        from . import proofs

        servers["proofs"] = proofs.PROOFS_SERVER
    except Exception:
        pass
    try:
        from . import gen_ui

        servers["gen_ui"] = gen_ui.GEN_UI_SERVER
    except Exception:
        pass
    try:
        from . import mesa

        servers["mesa"] = mesa.MESA_SERVER
    except Exception:
        pass
    try:
        from . import skill_lease

        servers["skill_lease"] = skill_lease.LEASE_SERVER
    except Exception:
        pass
    try:
        from . import causal

        servers["causal"] = causal.CAUSAL_SERVER
    except Exception:
        pass
    try:
        from . import adversarial

        servers["adversarial"] = adversarial.ADV_SERVER
    except Exception:
        pass
    # Playwright via npx — only register if npm is available; the SDK will
    # handle launch errors gracefully if the package can't be downloaded.
    if os.environ.get("CLAUDE_BOT_DISABLE_PLAYWRIGHT") != "1":
        servers["playwright"] = {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest", "--isolated"],
        }
    return servers


def build_options(session_id: str | None, chat_id: int | None = None) -> ClaudeAgentOptions:
    chat_extra = aliases_module.get_chat_sysprompt(chat_id) if chat_id else ""
    append_prompt = (
        "You are talking to the user over Telegram. Keep replies concise "
        "and well-formatted for a chat client. Avoid huge code blocks "
        "unless asked. Plain text or short markdown is preferred.\n\n"
        + memory_module.render_system_block()
    )
    if chat_extra:
        append_prompt += f"\n\n# Per-chat instructions\n{chat_extra}"
    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": append_prompt,
        },
        permission_mode="default",  # canUseTool gate
        skills="all",
        setting_sources=["user"],
        cwd=str(Path.home()),
        resume=session_id or None,
        include_partial_messages=False,
        mcp_servers=build_mcp_servers(),
        can_use_tool=approvals_module.can_use_tool,
        hooks=checkpoints_module.HOOKS_SPEC,
    )


# ---------- chat session ----------


async def _heartbeat(state: progress_module.RunState, bot) -> None:
    """Keep typing indicator alive and edit the status message periodically."""
    last_edit = 0.0
    while not state.finished:
        with contextlib.suppress(Exception):
            await bot.send_chat_action(chat_id=state.chat_id, action=ChatAction.TYPING)
        now = time.monotonic()
        if state.status_msg_id and (now - last_edit) >= progress_module.STATUS_EDIT_INTERVAL_SEC:
            last_edit = now
            with contextlib.suppress(Exception):
                await bot.edit_message_text(
                    chat_id=state.chat_id,
                    message_id=state.status_msg_id,
                    text=state.status_text(),
                    parse_mode=ParseMode.MARKDOWN,
                )
        try:
            await asyncio.sleep(progress_module.TYPING_INTERVAL_SEC)
        except asyncio.CancelledError:
            return


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Render the most useful one-liner summary of a tool call.

    Goal: glanceable in the Telegram status message — enough that the user
    knows exactly which file/command/URL/query is in flight.
    """
    if not isinstance(tool_input, dict):
        return ""
    ti = tool_input
    if tool_name == "Bash":
        return ti.get("command", "")
    if tool_name in ("Read", "Write", "NotebookEdit"):
        return ti.get("file_path") or ti.get("notebook_path") or ""
    if tool_name in ("Edit", "MultiEdit"):
        path = ti.get("file_path") or ""
        if tool_name == "MultiEdit" and "edits" in ti:
            return f"{path} ({len(ti['edits'])} edits)"
        return path
    if tool_name == "Grep":
        pat = ti.get("pattern", "")
        path = ti.get("path") or ti.get("glob") or ""
        return f"{pat}" + (f" in {path}" if path else "")
    if tool_name == "Glob":
        return ti.get("pattern", "")
    if tool_name == "WebFetch":
        return ti.get("url", "")
    if tool_name == "WebSearch":
        return ti.get("query", "")
    if tool_name == "Task":
        return ti.get("description") or ti.get("subagent_type") or ""
    if tool_name == "TodoWrite":
        todos = ti.get("todos") or []
        return f"{len(todos)} items"
    # MCP tools: pick a likely-useful field, otherwise show first ~80 chars
    for k in (
        "query",
        "name",
        "id",
        "target",
        "content",
        "find",
        "url",
        "path",
        "schedule",
        "title",
    ):
        if k in ti and isinstance(ti[k], str):
            return f"{k}={ti[k]}"
    # Fallback: stringify input
    try:
        import json as _json

        return _json.dumps(ti, ensure_ascii=False)
    except Exception:
        return str(ti)


async def _stream_claude(
    state: progress_module.RunState, prompt: str
) -> tuple[str, str | None, float | None, int | None, int | None]:
    """Run the Claude SDK call, updating `state` as messages arrive.

    Returns (concatenated_text, session_id, cost_usd, input_tokens, output_tokens).
    Honors state.cancel_event by interrupting the SDK client.
    """
    sid = topics_module.session_id_for(state.chat_id) or None
    options = build_options(sid, chat_id=state.chat_id)
    chunks: list[str] = []
    last_session: str | None = None
    cost = None
    in_tok = out_tok = None

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        async def consume():
            nonlocal last_session, cost, in_tok, out_tok
            async for msg in client.receive_response():
                if state.cancel_event.is_set():
                    with contextlib.suppress(Exception):
                        await client.interrupt()
                    raise asyncio.CancelledError("user-cancelled")
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            chunks.append(block.text)
                            state.text_chars += len(block.text)
                        elif isinstance(block, ToolUseBlock):
                            state.tool_calls.append(
                                progress_module.ToolEvent(
                                    name=block.name,
                                    summary=_summarize_tool_input(block.name, block.input),
                                )
                            )
                elif isinstance(msg, SystemMessage):
                    new_sid = (msg.data or {}).get("session_id")
                    if new_sid:
                        last_session = new_sid
                        # Persist immediately so a hang or crash doesn't lose recall.
                        with contextlib.suppress(Exception):
                            topics_module.set_session_id(state.chat_id, new_sid)
                elif isinstance(msg, ResultMessage):
                    if msg.session_id:
                        last_session = msg.session_id
                        with contextlib.suppress(Exception):
                            topics_module.set_session_id(state.chat_id, msg.session_id)
                    cost = getattr(msg, "total_cost_usd", None)
                    u = getattr(msg, "usage", None)
                    if isinstance(u, dict):
                        in_tok = u.get("input_tokens")
                        out_tok = u.get("output_tokens")

        await consume()

    return "".join(chunks).strip(), last_session, cost, in_tok, out_tok


async def ask_claude_with_progress(
    chat_id: int,
    prompt: str,
    bot,
    status_msg_id: int | None,
) -> str:
    """Run Claude with timeout, heartbeat, and cancellation.

    Returns the final reply text. May raise asyncio.TimeoutError or CancelledError.
    """
    state = progress_module.start(chat_id, status_msg_id)
    hb = asyncio.create_task(_heartbeat(state, bot))
    try:
        text, sid, cost, in_tok, out_tok = await asyncio.wait_for(
            _stream_claude(state, prompt),
            timeout=progress_module.REQUEST_TIMEOUT_SEC,
        )
        if sid:
            topics_module.set_session_id(chat_id, sid)
        usage_module.record(
            chat_id=str(chat_id),
            job_id=None,
            session_id=sid,
            cost_usd=cost,
            input_tokens=in_tok,
            output_tokens=out_tok,
            extra={"topic": topics_module.active_topic(chat_id)},
        )
        return redact(text) or "(no response)"
    finally:
        progress_module.end(chat_id)
        hb.cancel()
        # CancelledError inherits from BaseException in 3.11+ and would
        # otherwise leak out and look like the user cancelled the run.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await hb


# ---------- helpers ----------


def _authorized(update: Update) -> bool:
    if not ALLOWED_USERS:
        return True
    user = update.effective_user
    return bool(user and user.id in ALLOWED_USERS)


async def _send_long(update: Update, text: str) -> None:
    text = text.strip()
    if not text:
        return
    for i in range(0, len(text), TELEGRAM_MAX):
        chunk = text[i : i + TELEGRAM_MAX]
        try:
            await update.effective_message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.effective_message.reply_text(chunk)


# ---------- commands ----------


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.effective_message.reply_text(
        "Claude is online.\n\n"
        "*Commands*\n"
        "/reset — clear current topic's session\n"
        "/topic <name> — switch sub-conversation\n"
        "/topics — list topics in this chat\n"
        "/memory [memory|user] — view persistent memory\n"
        "/jobs — list cron jobs\n"
        "/runjob <id> — run a cron job now\n"
        "/kanban — view task board\n"
        "/usage — token & cost summary\n"
        "/rollback — restore most recent checkpoint\n"
        "/status — show in-flight request progress\n"
        "/cancel — abort current request\n"
        "/whoami — show your Telegram id",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_reset(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    topics_module.reset(chat_id)
    await update.effective_message.reply_text(
        f"Topic '{topics_module.active_topic(chat_id)}' reset."
    )


async def cmd_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text(
            f"current topic: `{topics_module.active_topic(update.effective_chat.id)}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    name = ctx.args[0].strip().lower()
    topics_module.switch(update.effective_chat.id, name)
    await update.effective_message.reply_text(
        f"switched to topic: `{name}`", parse_mode=ParseMode.MARKDOWN
    )


async def cmd_topics(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    rows = topics_module.list_topics(update.effective_chat.id)
    if not rows:
        await update.effective_message.reply_text("(no topics yet)")
        return
    lines = [
        f"{'➡️ ' if active else '   '}`{name}` {'(has session)' if has_sess else '(empty)'}"
        for name, active, has_sess in rows
    ]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    target = (ctx.args[0].lower() if ctx.args else "both").strip()
    if target not in ("memory", "user", "both"):
        await update.effective_message.reply_text("Usage: /memory [memory|user|both]")
        return
    blocks: list[str] = []
    for which in ("memory", "user") if target == "both" else (target,):
        entries = memory_module.list_entries(which)
        cap = memory_module.MEMORY_CAP if which == "memory" else memory_module.USER_CAP
        chars = memory_module.total_chars(which)
        header = f"*{which.upper()}.md* — {chars}/{cap} chars, {len(entries)} entries"
        body = "\n".join(f"• {e}" for e in entries) if entries else "_(empty)_"
        blocks.append(header + "\n" + body)
    text = "\n\n".join(blocks)
    for i in range(0, len(text), TELEGRAM_MAX):
        try:
            await update.effective_message.reply_text(
                text[i : i + TELEGRAM_MAX], parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.effective_message.reply_text(text[i : i + TELEGRAM_MAX])


async def cmd_journal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    n = 5
    if ctx.args:
        with contextlib.suppress(ValueError):
            n = max(1, min(20, int(ctx.args[0])))
    text = self_improve_module.read_recent_journal(n)
    for i in range(0, len(text), TELEGRAM_MAX):
        try:
            await update.effective_message.reply_text(
                text[i : i + TELEGRAM_MAX], parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.effective_message.reply_text(text[i : i + TELEGRAM_MAX])


async def cmd_improve(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    await update.effective_message.reply_text("🔄 running self-improvement turn now…")
    asyncio.create_task(self_improve_module.run_daily(ctx.bot, deliver_to=str(chat_id)))


async def cmd_insights(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.effective_message.reply_text(
        usage_module.insights(), parse_mode=ParseMode.MARKDOWN
    )


async def cmd_aliases(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    al = aliases_module.list_aliases()
    if not al:
        await update.effective_message.reply_text(
            "_(no aliases yet)_\n\nDefine: `/alias name = template`\n"
            "Use $1 $2 ... or $* for arguments.\n"
            "Example: `/alias summarize = Summarize this URL: $1`\n"
            "Run: `/run <name> <args>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    lines = [f"`/run {n}` — {t[:80]}" for n, t in al.items()]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_alias(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text(
            "Usage: `/alias name = template` (or `/alias name -` to delete)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    raw = " ".join(ctx.args)
    if "=" not in raw and not raw.endswith(" -"):
        await update.effective_message.reply_text("Need `=` between name and template.")
        return
    if raw.endswith(" -"):
        name = raw[:-2].strip()
        if aliases_module.remove_alias(name):
            await update.effective_message.reply_text(
                f"removed alias `{name}`", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.effective_message.reply_text(f"no such alias: {name}")
        return
    name, _, template = raw.partition("=")
    name = name.strip()
    template = template.strip()
    if not name or not template:
        await update.effective_message.reply_text("name and template both required.")
        return
    aliases_module.set_alias(name, template)
    await update.effective_message.reply_text(
        f"saved alias `{name}` → {template[:120]}", parse_mode=ParseMode.MARKDOWN
    )


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /run <alias-name> [args…]")
        return
    name = ctx.args[0]
    args = ctx.args[1:]
    template = aliases_module.get_alias(name)
    if template is None:
        await update.effective_message.reply_text(f"no alias: {name}")
        return
    rendered = aliases_module.render(template, args)
    # Forward through the normal message path
    update.message.text = rendered
    await on_message(update, ctx)


async def cmd_sysprompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    if not ctx.args:
        cur = aliases_module.get_chat_sysprompt(chat_id)
        await update.effective_message.reply_text(
            f"_current chat sysprompt:_\n\n{cur or '(none)'}\n\nSet: /sysprompt <text>\nClear: /sysprompt -",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    text = " ".join(ctx.args)
    if text.strip() == "-":
        aliases_module.set_chat_sysprompt(chat_id, "")
        await update.effective_message.reply_text("chat sysprompt cleared")
        return
    aliases_module.set_chat_sysprompt(chat_id, text)
    await update.effective_message.reply_text(f"chat sysprompt set: {text[:120]}")


async def cmd_providers(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """List all supported AI providers and which keys are configured."""
    if not _authorized(update):
        return
    from .providers import list_providers

    catalog = list_providers()
    lines = ["*Available AI providers* (BYO key for any)"]
    for name, info in catalog.items():
        # Cheap "is key set" check
        env_var = info["key_env"].split(" ")[0]
        configured = "✅" if os.environ.get(env_var) else "  "
        lines.append(f"{configured} `{name}` — {info['label']}")
    lines.append("")
    lines.append(
        "Switch with `/model <provider> [model]` or globally via OPENGRIFFIN_PROVIDER env."
    )
    text = "\n".join(lines)
    for i in range(0, len(text), TELEGRAM_MAX):
        try:
            await update.effective_message.reply_text(
                text[i : i + TELEGRAM_MAX], parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.effective_message.reply_text(text[i : i + TELEGRAM_MAX])


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the AI provider/model for this chat."""
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    if not ctx.args:
        cur = aliases_module.get_chat_model(chat_id)
        prov = cur.get("provider") or os.environ.get("OPENGRIFFIN_PROVIDER", "claude")
        model = cur.get("model") or os.environ.get("OPENGRIFFIN_MODEL") or "(provider default)"
        await update.effective_message.reply_text(
            f"_current:_ `{prov}` / `{model}`\n\n"
            "Set: `/model <provider> [model]`\n"
            "List providers: /providers\n"
            "Reset: `/model -`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if ctx.args[0].strip() == "-":
        aliases_module.set_chat_model(chat_id, None, None)
        await update.effective_message.reply_text("reset to default provider")
        return
    from .providers import list_providers

    catalog = list_providers()
    provider = ctx.args[0].strip().lower()
    if provider not in catalog:
        await update.effective_message.reply_text(
            f"unknown provider `{provider}`. Try /providers", parse_mode=ParseMode.MARKDOWN
        )
        return
    model = ctx.args[1].strip() if len(ctx.args) > 1 else None
    aliases_module.set_chat_model(chat_id, provider, model)
    label = catalog[provider]["label"]
    msg = f"✓ this chat now uses *{label}*"
    if model:
        msg += f" / `{model}`"
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_personality(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    presets_file = memory_module.MEM_DIR / "SOUL.presets.md"
    if not ctx.args:
        if presets_file.is_file():
            text = presets_file.read_text()
            for i in range(0, len(text), TELEGRAM_MAX):
                try:
                    await update.effective_message.reply_text(
                        text[i : i + TELEGRAM_MAX], parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    await update.effective_message.reply_text(text[i : i + TELEGRAM_MAX])
        else:
            await update.effective_message.reply_text(
                "no presets file. Edit ~/.opengriffin/memories/SOUL.md directly."
            )
        return
    name = ctx.args[0].strip().lower()
    if not presets_file.is_file():
        await update.effective_message.reply_text("presets file missing")
        return
    text = presets_file.read_text()
    import re as _re

    m = _re.search(rf"^## {_re.escape(name)}\s*$([\s\S]*?)(?=^## |\Z)", text, _re.MULTILINE)
    if not m:
        await update.effective_message.reply_text(
            f"no preset named '{name}'. /personality with no args lists them."
        )
        return
    body = m.group(1).strip()
    memory_module.SOUL_FILE.write_text(f"# Personality: {name}\n\n{body}\n")
    await update.effective_message.reply_text(
        f"applied personality: *{name}*", parse_mode=ParseMode.MARKDOWN
    )


async def cmd_recall(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /recall <substring>")
        return
    query = " ".join(ctx.args)
    hits = recall_module.search(query, since_days=60)
    text = recall_module.render(hits)
    for i in range(0, len(text), TELEGRAM_MAX):
        try:
            await update.effective_message.reply_text(
                text[i : i + TELEGRAM_MAX], parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.effective_message.reply_text(text[i : i + TELEGRAM_MAX])


async def cmd_sessions(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    archive = topics_module.list_archive(chat_id)
    if not archive:
        await update.effective_message.reply_text(
            "_(no archived sessions)_", parse_mode=ParseMode.MARKDOWN
        )
        return
    lines = []
    for entry in archive[:20]:
        sid = entry.get("session_id", "")
        topic = entry.get("topic", "?")
        ts = entry.get("archived_at", "?")
        lines.append(f"`{sid[:8]}` — topic *{topic}* — archived {ts}")
    text = "\n".join(lines)
    text += "\n\nResume with: `/resume <session_id_prefix>`"
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /resume <session_id or 8-char prefix>")
        return
    chat_id = update.effective_chat.id
    prefix = ctx.args[0].strip()
    archive = topics_module.list_archive(chat_id)
    match = next((e for e in archive if e["session_id"].startswith(prefix)), None)
    if match is None:
        await update.effective_message.reply_text(f"no archived session matches: {prefix}")
        return
    ok = topics_module.restore_archived(chat_id, match["session_id"])
    if ok:
        await update.effective_message.reply_text(
            f"✓ resumed `{match['session_id'][:8]}` (topic *{match['topic']}*). Send a message to continue.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.effective_message.reply_text("resume failed")


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    state = progress_module.get(chat_id)
    if state is None or state.finished:
        await update.effective_message.reply_text(
            "_(no active request)_", parse_mode=ParseMode.MARKDOWN
        )
        return
    await update.effective_message.reply_text(state.status_text(), parse_mode=ParseMode.MARKDOWN)


async def cmd_cancel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    if progress_module.cancel(chat_id):
        await update.effective_message.reply_text("⏹ cancelling…")
    else:
        await update.effective_message.reply_text("(no active request)")


async def cmd_jobs(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    sched = botctx.CTX.scheduler
    if sched is None:
        await update.effective_message.reply_text("No scheduler running.")
        return
    lines: list[str] = []
    for j in sched.get_jobs():
        nxt = j.next_run_time.strftime("%Y-%m-%d %H:%M %Z") if j.next_run_time else "—"
        lines.append(f"• `{j.id}` — {j.name}\n  next: {nxt}")
    await update.effective_message.reply_text(
        "\n".join(lines) if lines else "No jobs scheduled.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_runjob(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /runjob <job_id>")
        return
    job_id = ctx.args[0]
    jobs = cron_module.load_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if job is None:
        await update.effective_message.reply_text(f"Unknown job: {job_id}")
        return
    await update.effective_message.reply_text(f"Running {job.id}…")
    asyncio.create_task(cron_module.run_job(job, ctx.bot))


async def cmd_usage(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.effective_message.reply_text(usage_module.summary(), parse_mode=ParseMode.MARKDOWN)


async def cmd_rollback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    ok, msg = checkpoints_module.rollback_latest()
    await update.effective_message.reply_text(msg if ok else f"rollback failed: {msg}")


async def cmd_kanban(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.effective_message.reply_text(
        kanban_module.render_board(), parse_mode=ParseMode.MARKDOWN
    )


async def cmd_whoami(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    await update.effective_message.reply_text(
        f"user_id: {user.id if user else '?'}\n"
        f"chat_id: {chat.id if chat else '?'}\n"
        f"authorized: {_authorized(update)}\n"
        f"topic: {topics_module.active_topic(chat.id) if chat else '?'}"
    )


# ---------- message handlers ----------


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        log.info("Unauthorized message from %s", update.effective_user)
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    chat_id = update.effective_chat.id

    if progress_module.is_running(chat_id):
        await update.effective_message.reply_text(
            "_(still working on a previous request — /status or /cancel)_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Send a status message we'll keep editing as the run progresses.
    status_msg = None
    try:
        msg = await update.effective_message.reply_text(
            "🤔 thinking…", parse_mode=ParseMode.MARKDOWN
        )
        status_msg = msg.message_id
    except Exception:
        pass

    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        reply = await ask_claude_with_progress(chat_id, text, ctx.bot, status_msg)
    except TimeoutError:
        msg = (
            f"⏱ Timed out after {progress_module.REQUEST_TIMEOUT_SEC}s. "
            "The Claude subprocess didn't return a final response. "
            "Try /reset and resend."
        )
        if status_msg:
            try:
                await ctx.bot.edit_message_text(chat_id=chat_id, message_id=status_msg, text=msg)
                return
            except Exception:
                pass
        await update.effective_message.reply_text(msg)
        return
    except asyncio.CancelledError:
        msg = "❎ cancelled"
        if status_msg:
            try:
                await ctx.bot.edit_message_text(chat_id=chat_id, message_id=status_msg, text=msg)
                return
            except Exception:
                pass
        await update.effective_message.reply_text(msg)
        return
    except Exception as e:
        log.exception("Claude error")
        err = f"Error: {e}"
        if status_msg:
            try:
                await ctx.bot.edit_message_text(chat_id=chat_id, message_id=status_msg, text=err)
                return
            except Exception:
                pass
        await update.effective_message.reply_text(err)
        return

    # Replace the status message with the start of the reply, send overflow
    # as separate messages.
    if status_msg and reply:
        head = reply[:TELEGRAM_MAX]
        try:
            await ctx.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg, text=head, parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            with contextlib.suppress(Exception):
                await ctx.bot.edit_message_text(chat_id=chat_id, message_id=status_msg, text=head)
        if len(reply) > TELEGRAM_MAX:
            for i in range(TELEGRAM_MAX, len(reply), TELEGRAM_MAX):
                chunk = reply[i : i + TELEGRAM_MAX]
                try:
                    await update.effective_message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await update.effective_message.reply_text(chunk)
    else:
        await _send_long(update, reply)


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    voice = update.message.voice or update.message.audio
    if voice is None:
        return
    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
    try:
        f = await voice.get_file()
        ogg_bytes = await f.download_as_bytearray()
        text = await voice_module.transcribe_ogg(bytes(ogg_bytes))
    except Exception as e:
        log.exception("voice transcription failed")
        await update.effective_message.reply_text(f"voice transcription failed: {e}")
        return
    if not text.strip():
        await update.effective_message.reply_text("(empty transcription)")
        return
    await update.effective_message.reply_text(f"_(heard:_ {text}_)_", parse_mode=ParseMode.MARKDOWN)
    if progress_module.is_running(chat_id):
        await update.effective_message.reply_text("(busy — /cancel first)")
        return
    status = None
    try:
        m = await update.effective_message.reply_text("🤔 thinking…")
        status = m.message_id
    except Exception:
        pass
    try:
        reply = await ask_claude_with_progress(chat_id, text, ctx.bot, status)
    except (TimeoutError, asyncio.CancelledError) as e:
        await update.effective_message.reply_text(f"voice run aborted: {type(e).__name__}")
        return
    except Exception as e:
        log.exception("Claude error on voice")
        await update.effective_message.reply_text(f"Error: {e}")
        return

    # Reply with voice (truncate if very long).
    short = reply[:1500]
    try:
        ogg = await voice_module.synthesize_ogg(short)
        await ctx.bot.send_voice(chat_id=chat_id, voice=ogg)
    except Exception:
        log.exception("TTS failed")
    # Always also send the text so nothing is lost.
    await _send_long(update, reply)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled error", exc_info=context.error)


# ---------- background jobs ----------


_MEMORY_EXTRACTION_PROMPT = (
    "Daily wrap-up. Before this session is archived, review the conversation "
    "and persist anything durable using the memory tools:\n"
    "- Use `memory_add` with target='user' for new user preferences, "
    "  habits, ongoing projects, or in-flight tasks the user expects to "
    "  resume later.\n"
    "- Use `memory_add` with target='memory' for environment facts, gotchas, "
    "  or lessons that apply to future sessions.\n"
    "Skip duplicates. Be terse. If nothing is worth saving, say so. "
    "After saving, reply in ONE LINE summarizing what you persisted (or 'nothing new')."
)


async def _idle_reset_all() -> None:
    """Daily 4am: memory-extraction turn on each active session, then archive.

    Per the bot pattern: don't just drop the session — first give the agent a
    turn to write durable facts to MEMORY/USER files, THEN archive the
    session_id (recoverable via /sessions /resume) and start fresh.
    """
    if botctx.CTX.bot is None:
        return
    archived = 0
    saved_count = 0
    chat_ids = list(topics_module._chats.keys())
    for chat_id in chat_ids:
        topics_state = topics_module._chats.get(chat_id)
        if topics_state is None:
            continue
        for topic_name in list(topics_state.sessions.keys()):
            sid = topics_state.sessions.get(topic_name)
            if not sid:
                topics_state.sessions.pop(topic_name, None)
                continue
            # Run a memory-extraction turn against this session.
            if progress_module.is_running(chat_id):
                log.info("Skipping memory extraction for chat %s (run in flight)", chat_id)
                continue
            try:
                topics_state.active = topic_name  # ensure ask_claude resumes the right one
                topics_module._flush()
                _ = await asyncio.wait_for(
                    ask_claude_with_progress(
                        chat_id, _MEMORY_EXTRACTION_PROMPT, botctx.CTX.bot, status_msg_id=None
                    ),
                    timeout=180,
                )
                saved_count += 1
            except Exception:
                log.exception("memory extraction failed for chat=%s topic=%s", chat_id, topic_name)
            # Archive the session_id so the user can resume later if needed.
            topics_module.reset(chat_id, topic_name, archive=True)
            archived += 1
    log.info(
        "Daily reset: ran memory extraction on %d sessions, archived %d", saved_count, archived
    )


# ---------- lifecycle ----------


async def _post_init(app: Application) -> None:
    scheduler = AsyncIOScheduler()
    cron_module.install_jobs(scheduler, app.bot)
    scheduler.add_job(
        _idle_reset_all,
        trigger=CronTrigger(hour=IDLE_RESET_HOUR, minute=0),
        id="__daily_session_reset",
        name="daily session reset",
        replace_existing=True,
    )
    scheduler.add_job(
        self_improve_module.run_daily,
        kwargs={"bot": app.bot, "deliver_to": HOME_CHAT_ID},
        trigger=CronTrigger(hour=IDLE_RESET_HOUR, minute=30),
        id="__daily_self_improve",
        name="daily self-improvement",
        replace_existing=True,
    )
    # Echo memory nightly consolidation
    try:
        from . import echo_memory as _echo

        scheduler.add_job(
            _echo.consolidate_nightly,
            trigger=CronTrigger(hour=IDLE_RESET_HOUR, minute=45),
            id="__echo_consolidate",
            name="echo memory consolidation",
            replace_existing=True,
        )
    except Exception:
        pass
    # Drift detection nightly
    try:
        from . import drift as _drift

        scheduler.add_job(
            _drift.detect_drift,
            trigger=CronTrigger(hour=IDLE_RESET_HOUR + 1, minute=0),
            id="__drift_check",
            name="drift detection",
            replace_existing=True,
        )
    except Exception:
        pass
    # Voice-card refresh weekly
    try:
        from . import soul_sync as _soul

        scheduler.add_job(
            _soul.refresh_voice_card,
            trigger=CronTrigger(day_of_week="sun", hour=5, minute=0),
            id="__voice_refresh",
            name="voice card refresh",
            replace_existing=True,
        )
    except Exception:
        pass
    # Ambient triggers from triggers.json
    try:
        from . import triggers as _trig

        n = _trig.install_into_scheduler(scheduler)
        if n:
            log.info("Installed %d ambient triggers", n)
    except Exception:
        log.exception("trigger install failed")
    # Personal World Model — nightly retrain
    try:
        from . import world_model as _wm

        scheduler.add_job(
            _wm.train,
            trigger=CronTrigger(hour=IDLE_RESET_HOUR + 1, minute=15),
            id="__world_model_train",
            name="world model nightly retrain",
            replace_existing=True,
        )
    except Exception:
        pass
    # Mesa-cognition supervisor — nightly drift report
    try:
        from . import mesa as _mesa

        scheduler.add_job(
            _mesa.run_report,
            trigger=CronTrigger(hour=IDLE_RESET_HOUR + 1, minute=30),
            id="__mesa_report",
            name="mesa-cognition drift report",
            replace_existing=True,
        )
    except Exception:
        pass
    # Causal layer — daily edge discovery from world-model log
    try:
        from . import causal as _causal

        scheduler.add_job(
            _causal.discover_from_world_model,
            trigger=CronTrigger(hour=IDLE_RESET_HOUR + 1, minute=45),
            id="__causal_discover",
            name="causal edge discovery",
            replace_existing=True,
        )
    except Exception:
        pass
    scheduler.start()
    botctx.set_context(
        bot=app.bot,
        app=app,
        scheduler=scheduler,
        allowed_users=ALLOWED_USERS,
        home_chat_id=HOME_CHAT_ID,
    )
    # Start webhooks server
    app.bot_data["webhook_runner"] = await webhooks_module.start_server()
    log.info(
        "Scheduler started with %d jobs (incl. daily reset @ %02d:00)",
        len(scheduler.get_jobs()),
        IDLE_RESET_HOUR,
    )


async def _post_shutdown(app: Application) -> None:
    if botctx.CTX.scheduler is not None:
        botctx.CTX.scheduler.shutdown(wait=False)
    runner = app.bot_data.get("webhook_runner")
    if runner is not None:
        await runner.cleanup()


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set")
    log.info("Allowed users: %s | home chat: %s", ALLOWED_USERS or "(open)", HOME_CHAT_ID)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("topic", cmd_topic))
    app.add_handler(CommandHandler("topics", cmd_topics))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("jobs", cmd_jobs))
    app.add_handler(CommandHandler("runjob", cmd_runjob))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(CommandHandler("rollback", cmd_rollback))
    app.add_handler(CommandHandler("kanban", cmd_kanban))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("recall", cmd_recall))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("journal", cmd_journal))
    app.add_handler(CommandHandler("improve", cmd_improve))
    app.add_handler(CommandHandler("insights", cmd_insights))
    app.add_handler(CommandHandler("aliases", cmd_aliases))
    app.add_handler(CommandHandler("alias", cmd_alias))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("sysprompt", cmd_sysprompt))
    app.add_handler(CommandHandler("personality", cmd_personality))
    app.add_handler(CommandHandler("providers", cmd_providers))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(approvals_module.HANDLER)
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    log.info("Starting bot…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
