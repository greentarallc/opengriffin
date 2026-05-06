"""Daily self-improvement loop.

Runs at 4:30am after the 4am reset. Has the bot review its own state
through a Claude session and:

  1. Append a journal entry to ~/.opengriffin/memories/JOURNAL.md
     (yesterday's summary — what happened, what worked, what failed).
  2. Consolidate MEMORY.md / USER.md if near cap (merge dupes, drop stale).
  3. Surface failures from yesterday's session transcripts.
  4. Suggest new skills it could create from observed patterns.
  5. Tag any in-progress kanban tasks that have stalled.
  6. Cap JOURNAL.md to last 90 entries to keep it bounded.

Designed to be IDEMPOTENT — safe to run twice in a day, won't double-write.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("opengriffin.self_improve")

BOT_DIR = Path(__file__).resolve().parent
MEM_DIR = BOT_DIR / "memories"
JOURNAL_FILE = MEM_DIR / "JOURNAL.md"
USAGE_FILE = BOT_DIR / "usage.jsonl"
JOURNAL_MAX_ENTRIES = 90


SELF_IMPROVE_PROMPT = """\
You are running the daily self-improvement turn for a Telegram bot. Today's date: {today}. \
Yesterday: {yesterday}.

Your job is to review yesterday's activity and improve the bot's persistent state. Be terse \
and structured. Use the tools you have access to (memory_*, session_search, kanban_*, \
skill_*, image_generate, cronjob_*, send_message). Do NOT message the user — your output \
goes to a log.

REQUIRED STEPS, in order:

1. **Recap**: use `session_search` to look at yesterday's conversations (search a few likely \
substrings if useful, or just sample recent sessions). Build a 3-5 line recap of what \
happened, what got done, and what the user seemed to care about.

2. **Memory hygiene**: read MEMORY.md and USER.md from the system prompt block. If either \
is over 80% of its cap, use `memory_replace` and `memory_remove` to consolidate (merge \
similar entries, drop stale items, prefer the most recent durable facts). Stop when both \
are under 70%.

3. **Persist new lessons**: from yesterday's recap, add any NEW durable facts via \
`memory_add` — user preferences to USER, environment/project facts to MEMORY. No duplicates.

4. **Failure surface**: search for "Error:" / "failed" / "timeout" in recent sessions. List \
each genuine failure (not transient network blips) in the journal and assign a severity \
{{low|med|high}}. If high-severity, mention it explicitly.

5. **Skill suggestions**: if you see a workflow that recurred 3+ times in recent sessions \
or could plausibly recur, propose a NEW skill name + 1-line description. Don't create the \
skill — just propose it. The user will approve.

6. **Kanban check**: list any kanban tasks in 'doing' status older than 48 hours. Flag them.

7. **Append journal entry**: at the END, write the journal entry to disk by calling the \
`journal_append` tool with a structured payload containing today's date and your findings. \
This is the only durable output of this turn.

Format the journal_append `entry` argument as compact markdown with these sections:
```
## {today}
**Recap:** <3-5 lines>
**Memory:** <one line: did you consolidate? added how many?>
**Failures:** <list each, one per line, or "none">
**Suggested skills:** <list or "none">
**Stalled kanban:** <list or "none">
**Notes:** <anything else worth remembering for tomorrow's self>
```

End your response with the literal token `<DONE>` so the harness knows you finished cleanly.
"""


# --- journal management ---


def _ensure_files() -> None:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    if not JOURNAL_FILE.is_file():
        JOURNAL_FILE.write_text("# Bot Daily Journal\n\n")


def append_journal_entry(entry: str) -> None:
    """Append entry to JOURNAL.md and trim to last N entries."""
    _ensure_files()
    text = JOURNAL_FILE.read_text()
    text = text.rstrip() + "\n\n" + entry.strip() + "\n"
    # Trim to last N entries by splitting on '## ' headers (date markers)
    parts = text.split("\n## ")
    if len(parts) > JOURNAL_MAX_ENTRIES + 1:
        # Keep the header + last N entries
        text = parts[0].rstrip() + "\n\n## " + "\n## ".join(parts[-JOURNAL_MAX_ENTRIES:]).strip() + "\n"
    JOURNAL_FILE.write_text(text)


def read_recent_journal(n: int = 5) -> str:
    if not JOURNAL_FILE.is_file():
        return "(no journal)"
    text = JOURNAL_FILE.read_text()
    # Split on '\n## ' and take last n
    parts = text.split("\n## ")
    if len(parts) <= 1:
        return text.strip() or "(empty journal)"
    return "## " + "\n## ".join(parts[-n:]).strip()


# --- usage stats helpers ---


def yesterday_stats() -> dict:
    if not USAGE_FILE.is_file():
        return {"runs": 0}
    cutoff_start = dt.datetime.combine(
        dt.date.today() - dt.timedelta(days=1), dt.time(0, 0)
    )
    cutoff_end = dt.datetime.combine(dt.date.today(), dt.time(0, 0))
    runs = 0
    cost = 0.0
    in_tok = out_tok = 0
    cron_runs = 0
    chat_runs = 0
    for line in USAGE_FILE.read_text().splitlines():
        try:
            e = json.loads(line)
            ts = dt.datetime.fromisoformat(e["ts"])
        except Exception:
            continue
        if not (cutoff_start <= ts < cutoff_end):
            continue
        runs += 1
        cost += e.get("cost_usd") or 0
        in_tok += e.get("input_tokens") or 0
        out_tok += e.get("output_tokens") or 0
        if e.get("job_id"):
            cron_runs += 1
        elif e.get("chat_id"):
            chat_runs += 1
    return {
        "runs": runs,
        "cost_usd": round(cost, 4),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cron_runs": cron_runs,
        "chat_runs": chat_runs,
    }


# --- the daily run ---


async def run_daily(bot, deliver_to: Optional[str] = None) -> str:
    """Execute the daily self-improvement turn. Returns a short status string."""
    from . import bot as bot_module  # local import to avoid circular

    today = dt.date.today().isoformat()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    stats = yesterday_stats()
    prompt = SELF_IMPROVE_PROMPT.format(today=today, yesterday=yesterday)
    prompt += f"\n\nYesterday's usage stats: {json.dumps(stats)}\n"

    log.info("Starting daily self-improvement turn for %s", today)
    try:
        result = await bot_module.ask_claude_with_progress(
            chat_id=int(deliver_to) if deliver_to else 0,
            prompt=prompt,
            bot=bot,
            status_msg_id=None,
        )
    except Exception as e:
        log.exception("self-improvement run failed")
        return f"self-improvement failed: {e}"

    if deliver_to and bot is not None:
        try:
            preview = read_recent_journal(1)
            await bot.send_message(
                chat_id=deliver_to,
                text=f"📝 *Daily journal*\n\n{preview}",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    return f"self-improvement done ({len(result)} chars in reply)"
