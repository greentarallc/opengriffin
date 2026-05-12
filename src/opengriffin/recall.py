"""Search past Claude sessions stored on disk by Claude Code.

Each session is a JSONL file at ~/.claude/projects/<encoded-cwd>/<session_id>.jsonl
containing the full message history. We grep across them for substring
matches and return short snippets with the session_id + timestamp so the
agent (or user) can resume one if a match is found.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

PROJECTS_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_PROJECT = "-Users-macmini"  # bot runs with cwd=$HOME
MAX_RESULTS = 10
SNIPPET_CHARS = 240


@dataclass
class SearchHit:
    session_id: str
    project: str
    mtime: dt.datetime
    role: str
    snippet: str


def _projects() -> list[Path]:
    if not PROJECTS_ROOT.is_dir():
        return []
    return [p for p in PROJECTS_ROOT.iterdir() if p.is_dir()]


def _iter_messages(jsonl: Path):
    try:
        with jsonl.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except OSError:
        return


def _extract_text(msg: dict) -> tuple[str, str]:
    """Return (role, plain_text) extracted from a stored message line."""
    role = msg.get("role") or msg.get("type") or "?"
    content = msg.get("content")
    if isinstance(content, str):
        return role, content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") == "text":
                    parts.append(c.get("text", ""))
                elif c.get("type") == "tool_use":
                    parts.append(
                        f"[tool_use:{c.get('name', '?')} {json.dumps(c.get('input', {}))[:200]}]"
                    )
                elif c.get("type") == "tool_result":
                    inner = c.get("content")
                    if isinstance(inner, list):
                        for ic in inner:
                            if isinstance(ic, dict) and ic.get("type") == "text":
                                parts.append(ic.get("text", ""))
                    elif isinstance(inner, str):
                        parts.append(inner)
        return role, "\n".join(parts)
    return role, ""


def search(query: str, *, project: str | None = None, since_days: int = 30) -> list[SearchHit]:
    """Substring (case-insensitive) search across session JSONL files."""
    if not query.strip():
        return []
    needle = query.lower()
    cutoff = dt.datetime.now() - dt.timedelta(days=since_days)
    targets: list[Path] = []
    if project:
        p = PROJECTS_ROOT / project
        if p.is_dir():
            targets = [p]
    else:
        targets = _projects()

    hits: list[SearchHit] = []
    files: list[tuple[Path, Path, dt.datetime]] = []
    for proj_dir in targets:
        for f in proj_dir.glob("*.jsonl"):
            try:
                mtime = dt.datetime.fromtimestamp(f.stat().st_mtime)
            except OSError:
                continue
            if mtime < cutoff:
                continue
            files.append((proj_dir, f, mtime))
    files.sort(key=lambda t: t[2], reverse=True)

    for proj_dir, f, mtime in files:
        if len(hits) >= MAX_RESULTS:
            break
        for msg in _iter_messages(f):
            role, text = _extract_text(msg)
            if not text:
                continue
            low = text.lower()
            if needle in low:
                idx = low.find(needle)
                start = max(0, idx - SNIPPET_CHARS // 2)
                snippet = text[start : start + SNIPPET_CHARS].strip().replace("\n", " ")
                hits.append(
                    SearchHit(
                        session_id=f.stem,
                        project=proj_dir.name,
                        mtime=mtime,
                        role=role,
                        snippet=snippet,
                    )
                )
                break  # one snippet per file
    return hits


def render(hits: list[SearchHit]) -> str:
    if not hits:
        return "(no matches)"
    lines = []
    for h in hits:
        ts = h.mtime.strftime("%Y-%m-%d %H:%M")
        lines.append(f"`{h.session_id[:8]}` ({ts}, {h.role})\n  {h.snippet[:300]}…")
    return "\n\n".join(lines)


# --- agent-callable MCP tool ---


@tool(
    "session_search",
    "Search past Claude sessions stored on disk for a substring. Returns session ids, timestamps, and snippets. Use this when the user references a prior conversation ('what did we discuss yesterday about X?', 'remember when I asked Y?').",
    {
        "query": Annotated[str, "Substring to search for (case-insensitive)"],
        "since_days": Annotated[int | None, "Look back this many days (default 30)"],
    },
)
async def _session_search(args: dict) -> dict:
    days = args.get("since_days") or 30
    hits = search(args["query"], since_days=int(days))
    text = render(hits)
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "session_load",
    "Load the full text of a past session by session_id. Use after session_search finds a relevant session.",
    {"session_id": Annotated[str, "Full or 8-char prefix of the session_id"]},
)
async def _session_load(args: dict) -> dict:
    sid = args["session_id"].strip()
    for proj_dir in _projects():
        for f in proj_dir.glob(f"{sid}*.jsonl"):
            messages = []
            for msg in _iter_messages(f):
                role, text = _extract_text(msg)
                if text:
                    messages.append(f"[{role}] {text}")
            return {"content": [{"type": "text", "text": "\n\n".join(messages)[:8000]}]}
    return {
        "content": [{"type": "text", "text": f"session not found: {sid}"}],
        "is_error": True,
    }


RECALL_SERVER = create_sdk_mcp_server(
    name="recall",
    version="1.0.0",
    tools=[_session_search, _session_load],
)
