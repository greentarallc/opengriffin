"""Drift Detection — flag when the agent's notes about the user contradict
each other or recent behavior contradicts past stated preferences.

Runs nightly on USER.md + JOURNAL entries. Asks the model to find
contradictions and surfaces them as gentle prompts ("3 months ago you
told me you hated meetings; today you scheduled five. Want to talk about it?").

Storage: drift.jsonl appended with each detected drift event.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.drift")

DRIFT_LOG = Path.home() / ".opengriffin" / "drift.jsonl"
DRIFT_LOG.parent.mkdir(parents=True, exist_ok=True)


DRIFT_PROMPT = """\
You are doing drift detection on a personal AI agent's user model. \
Look at USER.md preferences and the recent JOURNAL entries. List any \
contradictions or behavioral drift — moments where stated preferences \
disagree with recent activity. For each, output a JSON object on its own \
line:

{"severity": "low|med|high", "claim": "what USER.md says", "evidence": "what happened in JOURNAL", "suggestion": "<one-line gentle observation to surface to the user>"}

Output the JSON lines only. No preamble, no commentary. If no drift, output nothing.

USER.md:
{user_md}

Recent JOURNAL:
{journal}
"""


async def detect_drift() -> list[dict]:
    """Run a one-shot Claude analysis of USER.md + recent journal."""
    from . import bot as bot_module  # noqa

    user_md_path = Path.home() / ".opengriffin" / "memories" / "USER.md"
    journal_path = Path.home() / ".opengriffin" / "memories" / "JOURNAL.md"
    if not user_md_path.is_file() or not journal_path.is_file():
        return []
    user_md = user_md_path.read_text()
    # Last 14 days of journal entries
    journal_full = journal_path.read_text()
    parts = journal_full.split("\n## ")
    recent = "\n## ".join(parts[-14:]) if len(parts) > 1 else journal_full

    prompt = DRIFT_PROMPT.format(user_md=user_md, journal=recent[:12000])
    try:
        reply = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
    except Exception as e:
        log.warning("drift detect failed: %s", e)
        return []

    drifts: list[dict] = []
    for line in reply.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
            d["detected_at"] = dt.datetime.now().isoformat(timespec="seconds")
            drifts.append(d)
        except Exception:
            continue

    if drifts:
        with DRIFT_LOG.open("a") as fh:
            for d in drifts:
                fh.write(json.dumps(d) + "\n")
    return drifts


def list_recent(n: int = 10) -> list[dict]:
    if not DRIFT_LOG.is_file():
        return []
    out = []
    for line in DRIFT_LOG.read_text().splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


@tool(
    "drift_check",
    "Run drift detection now: look for contradictions between USER.md preferences and recent JOURNAL behavior. Returns a list of drift events with severity and gentle observations to surface.",
    {},
)
async def _check(args: dict) -> dict:
    drifts = await detect_drift()
    if not drifts:
        return {"content": [{"type": "text", "text": "no drift detected"}]}
    lines = [f"[{d.get('severity', '?')}] {d.get('suggestion', '?')}" for d in drifts]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


DRIFT_SERVER = create_sdk_mcp_server(
    name="drift",
    version="1.0.0",
    tools=[_check],
)
