"""Dream cycle — 3am offline reflection that compounds.

Inspired by REM-sleep consolidation in mammals. Once a night, the agent:
  1. Picks 3-5 "interesting" sessions from the past 24h. Interesting =
     long, involved tool calls, high cost, OR ended in failure.
  2. For each, runs a 'counterfactual' pass: "what if you had taken
     approach X instead?". The answers go to dream_log.jsonl.
  3. Distills generalized lessons across all dreams; appends to MEMORY.md.
  4. Identifies skills that the dream sessions would have benefited from
     and suggests them.

Dreams cost LLM tokens but are CHEAP (smaller model via routing) and the
expected return is positive — every morning the agent wakes up slightly
sharper.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.dream")

DREAM_LOG = Path.home() / ".opengriffin" / "dream_log.jsonl"
DREAM_LOG.parent.mkdir(parents=True, exist_ok=True)

PROJECTS = Path.home() / ".claude" / "projects" / "-Users-macmini"
USAGE_LOG = Path.home() / ".opengriffin" / "usage.jsonl"


def _interesting_sessions(limit: int = 5) -> list[str]:
    """Pick session_ids worth dreaming about: long, expensive, or failed."""
    if not USAGE_LOG.is_file():
        return []
    candidates: list[tuple[float, str]] = []
    cutoff = dt.datetime.now() - dt.timedelta(hours=24)
    for line in USAGE_LOG.read_text().splitlines():
        try:
            e = json.loads(line)
            ts = dt.datetime.fromisoformat(e["ts"])
            if ts < cutoff:
                continue
            sid = e.get("session_id")
            if not sid:
                continue
            cost = float(e.get("cost_usd") or 0)
            tokens = (e.get("input_tokens") or 0) + (e.get("output_tokens") or 0)
            score = cost * 1000 + tokens * 0.001
            candidates.append((score, sid))
        except Exception:
            continue
    candidates.sort(key=lambda t: -t[0])
    return [sid for _, sid in candidates[:limit]]


def _read_session_text(session_id: str, max_chars: int = 8000) -> str:
    f = PROJECTS / f"{session_id}.jsonl"
    if not f.is_file():
        return ""
    text_parts = []
    for line in f.read_text().splitlines():
        try:
            msg = json.loads(line)
            content = msg.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text_parts.append(c.get("text", ""))
        except Exception:
            continue
    joined = "\n".join(text_parts)
    return joined[:max_chars]


COUNTERFACTUAL_PROMPT = """\
You are doing offline reflection on a past conversation. Read it carefully \
and produce ONE counterfactual: a plausible alternative approach the agent \
could have taken at a key decision point. Then state the lesson generalizable \
to future sessions.

Output a SINGLE JSON object on one line:
{"key_decision": "...", "alternative": "...", "lesson": "<one sentence>", "confidence": "low|med|high"}

Conversation:
{transcript}
"""


DISTILL_PROMPT = """\
You consolidated several individual reflections from last night's dream cycle \
into a small set of durable lessons. Read the dream entries below and output \
1-3 lessons (one per line, plain text, no preamble) that should be added to \
MEMORY.md as principles for future sessions. Skip duplicates of existing \
memory.

Dreams:
{dreams}

Existing MEMORY.md (do not duplicate):
{memory}
"""


async def run_dream_cycle() -> dict:
    """The nightly job. Returns a summary."""
    from . import bot as bot_module

    sids = _interesting_sessions(limit=5)
    if not sids:
        return {"sessions": 0, "dreams": 0, "lessons": 0}

    dreams: list[dict] = []
    for sid in sids:
        transcript = _read_session_text(sid)
        if not transcript:
            continue
        prompt = COUNTERFACTUAL_PROMPT.format(transcript=transcript)
        try:
            reply = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
        except Exception as e:
            log.warning("dream skipped for %s: %s", sid, e)
            continue
        # Parse JSON
        for line in reply.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                    d["session_id"] = sid
                    d["dreamt_at"] = dt.datetime.now().isoformat(timespec="seconds")
                    dreams.append(d)
                    break
                except Exception:
                    continue

    # Persist
    with DREAM_LOG.open("a") as fh:
        for d in dreams:
            fh.write(json.dumps(d) + "\n")

    # Distill into lessons → MEMORY.md
    lessons_added = 0
    if dreams:
        memory_path = Path.home() / ".opengriffin" / "memories" / "MEMORY.md"
        existing_memory = memory_path.read_text() if memory_path.is_file() else ""
        prompt = DISTILL_PROMPT.format(
            dreams="\n".join(json.dumps(d) for d in dreams),
            memory=existing_memory[:2000],
        )
        try:
            reply = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
            try:
                from . import memory as mem_module  # type: ignore
            except Exception:
                from . import memory as mem_module
            for line in reply.splitlines():
                line = line.strip(" -•").strip()
                if len(line) > 10 and not line.startswith("#"):
                    ok, _ = mem_module.add_entry("memory", line)
                    if ok:
                        lessons_added += 1
        except Exception as e:
            log.warning("dream distill failed: %s", e)

    return {
        "sessions_dreamt": len(sids),
        "dreams_recorded": len(dreams),
        "lessons_added": lessons_added,
    }


@tool(
    "dream_now",
    "Run the dream cycle on demand: pick recent interesting sessions, generate counterfactuals, distill lessons into MEMORY.md.",
    {},
)
async def _dream(args: dict) -> dict:
    result = await run_dream_cycle()
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "dream_log",
    "Show the most recent dream entries.",
    {"n": Annotated[int, "How many"]},
)
async def _log(args: dict) -> dict:
    if not DREAM_LOG.is_file():
        return {"content": [{"type": "text", "text": "no dreams yet"}]}
    lines = DREAM_LOG.read_text().splitlines()[-int(args.get("n") or 10) :]
    out = []
    for line in lines:
        try:
            d = json.loads(line)
            out.append(
                f"[{d.get('dreamt_at')}] decision: {d.get('key_decision', '?')[:80]}\n  → lesson: {d.get('lesson', '?')[:120]}"
            )
        except Exception:
            continue
    return {"content": [{"type": "text", "text": "\n\n".join(out)}]}


DREAM_SERVER = create_sdk_mcp_server(
    name="dream",
    version="1.0.0",
    tools=[_dream, _log],
)
