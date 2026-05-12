"""Persistent memory for the Claude bot, modeled after the bot' memory system.

Two markdown files in ./memories/:
  - MEMORY.md (~MEMORY_CAP chars): agent's environment notes, project conventions, lessons.
  - USER.md   (~USER_CAP chars):   user profile — preferences, communication style, habits.

Entries are separated by `§` on its own line. The current contents are injected
into the system prompt at session start (frozen-snapshot pattern). The agent
manages entries via in-process MCP tools `memory_add`, `memory_replace`,
`memory_remove`. Changes persist immediately to disk but only appear in the
system prompt of the *next* session — same as the bot.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Annotated, Literal

from claude_agent_sdk import create_sdk_mcp_server, tool

BOT_DIR = Path(__file__).resolve().parent
MEM_DIR = BOT_DIR / "memories"
MEMORY_FILE = MEM_DIR / "MEMORY.md"
USER_FILE = MEM_DIR / "USER.md"
SOUL_FILE = MEM_DIR / "SOUL.md"
SEP = "§"

MEMORY_CAP = 2200
USER_CAP = 1375

_lock = threading.Lock()

Target = Literal["memory", "user"]


def _path(target: Target) -> Path:
    return MEMORY_FILE if target == "memory" else USER_FILE


def _cap(target: Target) -> int:
    return MEMORY_CAP if target == "memory" else USER_CAP


def _read(target: Target) -> str:
    p = _path(target)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _write(target: Target, text: str) -> None:
    p = _path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _split(text: str) -> list[str]:
    if not text.strip():
        return []
    raw = re.split(rf"^\s*{re.escape(SEP)}\s*$", text, flags=re.MULTILINE)
    return [chunk.strip() for chunk in raw if chunk.strip()]


def _join(entries: list[str]) -> str:
    return ("\n" + SEP + "\n").join(e.strip() for e in entries if e.strip())


def list_entries(target: Target) -> list[str]:
    with _lock:
        return _split(_read(target))


def total_chars(target: Target) -> int:
    return len(_join(list_entries(target)))


def add_entry(target: Target, content: str) -> tuple[bool, str]:
    content = content.strip()
    if not content:
        return False, "empty entry"
    from redact import looks_like_injection

    if looks_like_injection(content):
        return False, "rejected: entry matches a prompt-injection pattern"
    with _lock:
        entries = _split(_read(target))
        for e in entries:
            if e == content:
                return False, "duplicate"
        entries.append(content)
        joined = _join(entries)
        cap = _cap(target)
        if len(joined) > cap:
            return (
                False,
                f"would exceed {target} cap ({len(joined)}/{cap}); "
                "consolidate or remove existing entries first",
            )
        _write(target, joined)
        return True, f"added; {target} now {len(joined)}/{cap} chars"


def replace_entry(target: Target, find: str, replace: str) -> tuple[bool, str]:
    find = find.strip()
    replace = replace.strip()
    if not find or not replace:
        return False, "find/replace must be non-empty"
    with _lock:
        entries = _split(_read(target))
        matched = -1
        for i, e in enumerate(entries):
            if find in e:
                matched = i
                break
        if matched < 0:
            return False, f"no entry contained: {find[:80]}"
        entries[matched] = replace
        joined = _join(entries)
        cap = _cap(target)
        if len(joined) > cap:
            return (
                False,
                f"would exceed {target} cap ({len(joined)}/{cap})",
            )
        _write(target, joined)
        return True, f"replaced; {target} now {len(joined)}/{cap} chars"


def remove_entry(target: Target, find: str) -> tuple[bool, str]:
    find = find.strip()
    if not find:
        return False, "find must be non-empty"
    with _lock:
        entries = _split(_read(target))
        kept = [e for e in entries if find not in e]
        if len(kept) == len(entries):
            return False, f"no entry contained: {find[:80]}"
        _write(target, _join(kept))
        joined = _join(kept)
        return (
            True,
            f"removed {len(entries) - len(kept)}; {target} now {len(joined)}/{_cap(target)} chars",
        )


def read_soul() -> str:
    if not SOUL_FILE.is_file():
        return ""
    return SOUL_FILE.read_text(encoding="utf-8").strip()


def render_system_block() -> str:
    """Format the current memory contents for injection into the system prompt."""
    mem_entries = list_entries("memory")
    user_entries = list_entries("user")
    soul = read_soul()

    parts: list[str] = []
    if soul:
        parts.append("# Personality (SOUL.md)")
        parts.append(soul)
        parts.append("")
    parts.append("# Persistent Memory")
    parts.append(
        "Two memory stores below are loaded fresh at the start of every session. "
        "They are your long-term notes about the user and the environment. Treat "
        "them as authoritative context. To update them mid-session, call the "
        "`memory_add`, `memory_replace`, or `memory_remove` tools — changes "
        "persist immediately to disk but only appear in the system prompt of the "
        "*next* session."
    )

    mem_chars = len(_join(mem_entries))
    parts.append("")
    parts.append(f"## MEMORY.md ({mem_chars}/{MEMORY_CAP} chars — environment, projects, lessons)")
    if mem_entries:
        for e in mem_entries:
            parts.append(f"- {e}")
    else:
        parts.append("(empty)")

    user_chars = len(_join(user_entries))
    parts.append("")
    parts.append(f"## USER.md ({user_chars}/{USER_CAP} chars — user profile, preferences)")
    if user_entries:
        for e in user_entries:
            parts.append(f"- {e}")
    else:
        parts.append("(empty)")

    parts.append("")
    parts.append(
        "When the user reveals a durable preference, fact, or workflow detail, "
        "save it. When you learn an environment or project fact that matters for "
        "future sessions, save it. Avoid duplicates. Consolidate if entries grow "
        "stale or near the cap."
    )
    return "\n".join(parts)


# --- SDK tools the agent calls ---


@tool(
    "memory_add",
    "Add a new entry to persistent memory. Use 'memory' for environment/project/agent notes, 'user' for user preferences and profile facts. Entries persist across sessions.",
    {
        "target": Annotated[str, "Either 'memory' or 'user'"],
        "content": Annotated[str, "The memory entry text (one fact or note per call)"],
    },
)
async def _memory_add(args: dict) -> dict:
    target = args["target"]
    if target not in ("memory", "user"):
        return {
            "content": [{"type": "text", "text": "target must be 'memory' or 'user'"}],
            "is_error": True,
        }
    ok, msg = add_entry(target, args["content"])
    return {"content": [{"type": "text", "text": msg}], "is_error": not ok}


@tool(
    "memory_replace",
    "Replace an existing memory entry. Finds the first entry containing the substring 'find' and replaces the entire entry with 'replace'.",
    {
        "target": Annotated[str, "Either 'memory' or 'user'"],
        "find": Annotated[str, "Substring identifying the entry to replace"],
        "replace": Annotated[str, "The new full entry text"],
    },
)
async def _memory_replace(args: dict) -> dict:
    target = args["target"]
    if target not in ("memory", "user"):
        return {
            "content": [{"type": "text", "text": "target must be 'memory' or 'user'"}],
            "is_error": True,
        }
    ok, msg = replace_entry(target, args["find"], args["replace"])
    return {"content": [{"type": "text", "text": msg}], "is_error": not ok}


@tool(
    "memory_remove",
    "Remove memory entries containing the given substring.",
    {
        "target": Annotated[str, "Either 'memory' or 'user'"],
        "find": Annotated[str, "Substring identifying entries to remove"],
    },
)
async def _memory_remove(args: dict) -> dict:
    target = args["target"]
    if target not in ("memory", "user"):
        return {
            "content": [{"type": "text", "text": "target must be 'memory' or 'user'"}],
            "is_error": True,
        }
    ok, msg = remove_entry(target, args["find"])
    return {"content": [{"type": "text", "text": msg}], "is_error": not ok}


MEMORY_SERVER = create_sdk_mcp_server(
    name="memory",
    version="1.0.0",
    tools=[_memory_add, _memory_replace, _memory_remove],
)

MEMORY_TOOL_NAMES = [
    "mcp__memory__memory_add",
    "mcp__memory__memory_replace",
    "mcp__memory__memory_remove",
]
