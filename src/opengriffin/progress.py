"""Per-chat run state for in-flight Claude requests.

Tracks elapsed time, tool calls, and a Telegram status message that gets
edited periodically so the user sees liveness. Provides /status and /cancel
behavior plus enforces a global per-request timeout.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("opengriffin.progress")

# Hard timeout per chat request. The SDK has no built-in cap; without this a
# hung subprocess wedges the chat indefinitely.
REQUEST_TIMEOUT_SEC = 600  # 10 min for chat
TYPING_INTERVAL_SEC = 5  # Telegram typing indicator expires ~5s
STATUS_EDIT_INTERVAL_SEC = 12


@dataclass
class ToolEvent:
    name: str  # e.g. "Bash", "Read", "mcp__memory__memory_add"
    summary: str = ""  # human-readable "what" — file path, command, url, etc.


@dataclass
class RunState:
    chat_id: int
    started_at: float
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    status_msg_id: int | None = None
    tool_calls: list[ToolEvent] = field(default_factory=list)
    text_chars: int = 0
    finished: bool = False

    def elapsed(self) -> int:
        return int(time.monotonic() - self.started_at)

    @property
    def current_tool(self) -> ToolEvent | None:
        return self.tool_calls[-1] if self.tool_calls else None

    def status_text(self) -> str:
        elapsed = self.elapsed()
        if elapsed >= 60:
            mins, secs = divmod(elapsed, 60)
            elapsed_str = f"{mins}m{secs:02d}s"
        else:
            elapsed_str = f"{elapsed}s"

        parts = []
        cur = self.current_tool
        if cur is not None:
            label = _pretty_tool_label(cur.name)
            line = f"{label}"
            if cur.summary:
                line += f" `{_truncate(cur.summary, 200)}`"
            parts.append(line)
        else:
            parts.append("⚙️ thinking…")

        meta = [elapsed_str]
        if len(self.tool_calls) > 1:
            meta.append(f"step {len(self.tool_calls)}")
        if self.text_chars:
            meta.append(f"{self.text_chars} chars")
        parts.append(f"_{' · '.join(meta)}_")

        return "\n".join(parts)


_TOOL_ICONS = {
    "Bash": "🖥️ Bash",
    "Read": "📖 Read",
    "Write": "✏️ Write",
    "Edit": "✏️ Edit",
    "MultiEdit": "✏️ MultiEdit",
    "NotebookEdit": "📓 NotebookEdit",
    "Glob": "🔍 Glob",
    "Grep": "🔍 Grep",
    "WebFetch": "🌐 WebFetch",
    "WebSearch": "🌐 WebSearch",
    "Task": "🤖 Subagent",
    "TodoWrite": "📝 Todo",
}


def _pretty_tool_label(raw: str) -> str:
    if raw in _TOOL_ICONS:
        return _TOOL_ICONS[raw]
    if raw.startswith("mcp__"):
        # mcp__server__tool → "🔌 server·tool"
        rest = raw[len("mcp__") :]
        return f"🔌 {rest.replace('__', '·')}"
    return f"🔧 {raw}"


def _truncate(text: str, n: int) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


_running: dict[int, RunState] = {}


def get(chat_id: int) -> RunState | None:
    return _running.get(chat_id)


def is_running(chat_id: int) -> bool:
    s = _running.get(chat_id)
    return s is not None and not s.finished


def start(chat_id: int, status_msg_id: int | None) -> RunState:
    state = RunState(
        chat_id=chat_id,
        started_at=time.monotonic(),
        status_msg_id=status_msg_id,
    )
    _running[chat_id] = state
    return state


def end(chat_id: int) -> None:
    s = _running.get(chat_id)
    if s is not None:
        s.finished = True
    _running.pop(chat_id, None)


def cancel(chat_id: int) -> bool:
    s = _running.get(chat_id)
    if s is None or s.finished:
        return False
    s.cancel_event.set()
    return True
