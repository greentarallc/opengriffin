"""Self-Healing Skills — when a skill fails repeatedly, debug + propose a fix.

A skill is "failing" if its invocation produces an error or unhandled
exception in the bot run. The bot wraps each skill call; on failure, it
records the failure context. When failures pass a threshold (3 in 7 days
by default), the self-healing job:

  1. Reads the failing skill's SKILL.md
  2. Reads the recorded failure traces
  3. Asks Claude (via subagent) to propose an updated SKILL.md
  4. Writes the proposal to ~/.opengriffin/skill_proposals/<name>.md
  5. Notifies the user via Telegram with diff + accept/reject buttons

Acceptance applies the patch to ~/.claude/skills/<name>/SKILL.md.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.self_healing")

FAILURES_LOG = Path.home() / ".opengriffin" / "skill_failures.jsonl"
PROPOSALS_DIR = Path.home() / ".opengriffin" / "skill_proposals"
SKILLS_DIR = Path.home() / ".claude" / "skills"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
FAILURES_LOG.parent.mkdir(parents=True, exist_ok=True)

FAILURE_THRESHOLD = 3
FAILURE_WINDOW_DAYS = 7


def record_failure(skill_name: str, error: str, context: str = "") -> None:
    """Called by the bot when a skill invocation errors."""
    entry = {
        "skill": skill_name,
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "error": error[:500],
        "context": context[:500],
    }
    with FAILURES_LOG.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def recent_failures(skill_name: str) -> list[dict]:
    if not FAILURES_LOG.is_file():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(days=FAILURE_WINDOW_DAYS)
    out = []
    for line in FAILURES_LOG.read_text().splitlines():
        try:
            e = json.loads(line)
            if e.get("skill") != skill_name:
                continue
            ts = dt.datetime.fromisoformat(e["ts"])
            if ts >= cutoff:
                out.append(e)
        except Exception:
            continue
    return out


HEAL_PROMPT = """\
You are a self-healing skill maintainer. The skill below is failing in production. \
Read its SKILL.md and the recent failure traces, then propose an UPDATED \
SKILL.md that fixes the underlying issue. Output ONLY the new file content, \
in full, no commentary, no code fences, ready to overwrite the existing file. \
Preserve the original frontmatter except where the failure is due to outdated \
instructions there.

=== current SKILL.md ===
{current}

=== recent failures ({n}) ===
{failures}
"""


async def heal_skill(skill_name: str) -> dict:
    """Run the heal pipeline for one skill. Writes a proposal and returns its path."""
    from . import bot as bot_module
    p = SKILLS_DIR / skill_name / "SKILL.md"
    if not p.is_file():
        return {"ok": False, "error": f"no such skill: {skill_name}"}
    failures = recent_failures(skill_name)
    if len(failures) < FAILURE_THRESHOLD:
        return {"ok": False, "error": f"only {len(failures)} failures; threshold {FAILURE_THRESHOLD}"}
    failure_text = "\n\n".join(
        f"[{f['ts']}] {f['error']}\ncontext: {f['context']}" for f in failures[-FAILURE_THRESHOLD * 2:]
    )
    prompt = HEAL_PROMPT.format(current=p.read_text(), n=len(failures), failures=failure_text)
    try:
        proposed = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
    except Exception as e:
        return {"ok": False, "error": f"healer error: {e}"}

    proposal_path = PROPOSALS_DIR / f"{skill_name}.md"
    proposal_path.write_text(proposed)
    return {"ok": True, "proposal": str(proposal_path), "failures_observed": len(failures)}


def accept_proposal(skill_name: str) -> bool:
    proposal_path = PROPOSALS_DIR / f"{skill_name}.md"
    if not proposal_path.is_file():
        return False
    target = SKILLS_DIR / skill_name / "SKILL.md"
    if not target.parent.is_dir():
        return False
    # Backup current
    backup = target.with_suffix(".md.bak")
    target.replace(backup)
    proposal_path.replace(target)
    return True


@tool(
    "skill_heal",
    "Try to self-heal a failing skill. Reads recent failure traces and proposes an updated SKILL.md. Writes proposal to ~/.opengriffin/skill_proposals/.",
    {"name": Annotated[str, "Skill name"]},
)
async def _heal(args: dict) -> dict:
    result = await heal_skill(args["name"])
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "skill_heal_accept",
    "Apply a previously generated heal proposal — overwrites SKILL.md and keeps a .bak backup.",
    {"name": Annotated[str, "Skill name"]},
)
async def _accept(args: dict) -> dict:
    ok = accept_proposal(args["name"])
    return {"content": [{"type": "text", "text": "applied" if ok else "no proposal found"}], "is_error": not ok}


HEAL_SERVER = create_sdk_mcp_server(
    name="self_healing",
    version="1.0.0",
    tools=[_heal, _accept],
)
